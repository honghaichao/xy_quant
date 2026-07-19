"""遗传算法因子挖掘器 — 参考 WorldQuant Brain GA 范式。

基于 factor.expression 的 AST，自动做：
  - 表达式变异（node swap / operator change / function substitution）
  - 表达式交叉（子树互换）
  - IC 适应度评估
  - 多代迭代 + 精华保留

用法:
    miner = FactorMiner(data_df, forward_returns_df)
    top_factors = miner.evolve(generations=10, population_size=50)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from factor.expression import (
    BinaryOp, ConstNode, ExprNode, FactorExpr, FuncCall, UnaryOp, VarNode, parse_expr,
)
from utils.logger import get_logger

logger = get_logger("factor.ga_miner")


# ═══════════════════════════════════════════════════════════════
# 基础变量池 & 函数池
# ═══════════════════════════════════════════════════════════════

DEFAULT_VARIABLES = [
    "open", "high", "low", "close", "vol", "amount",
    "ma_5", "ma_10", "ma_20", "ma_60",
    "rsi_6", "rsi_12", "rsi_24",
    "macd_dif", "macd_dea", "macd_histogram",
    "kdj_k", "kdj_d", "kdj_j",
]

DEFAULT_FUNCTIONS = [
    "ts_delta", "ts_pct", "ts_mean", "ts_std", "ts_cross", "ts_corr",
    "rank", "zscore", "scale", "if_then", "sign", "abs", "min", "max",
]

DEFAULT_BINARY_OPS = [
    ("+", lambda a, b: BinaryOp(a, b, lambda x, y: x + y)),
    ("-", lambda a, b: BinaryOp(a, b, lambda x, y: x - y)),
    ("*", lambda a, b: BinaryOp(a, b, lambda x, y: x * y)),
    ("/", lambda a, b: BinaryOp(a, b, lambda x, y: x / (y + 1e-9))),
]

# ═══════════════════════════════════════════════════════════════
# Individual
# ═══════════════════════════════════════════════════════════════


@dataclass
class Individual:
    """种群个体 — 一条因子表达式。"""

    source: str
    name: str = ""
    fitness: float | None = None  # |IC|
    _ast: ExprNode | None = field(default=None, repr=False)

    @staticmethod
    def random(name: str = "") -> Individual:
        """随机生成一条表达式。"""
        variables = DEFAULT_VARIABLES
        src = Individual._random_expr(variables, 0)
        return Individual(source=src, name=name or f"ga_{_make_name(src)}")

    @staticmethod
    def from_source(source: str, name: str = "") -> Individual:
        return Individual(source=source, name=name or f"ga_{_make_name(source)}")

    @property
    def ast(self) -> ExprNode:
        if self._ast is None:
            self._ast = parse_expr(self.source)
        return self._ast

    def evaluate(self, scope_df: pd.DataFrame) -> pd.Series:
        scope: dict[str, pd.Series] = {}
        for col in scope_df.columns:
            scope[str(col)] = scope_df[col]
        scope["__index__"] = scope_df.index
        return self.ast.eval(scope)

    # ── random expression generation ─────────────────────────

    @staticmethod
    def _random_var(vars_list: list[str]) -> str:
        return random.choice(vars_list)

    @staticmethod
    def _random_func(vars_list: list[str], depth: int = 0) -> str:
        fn = random.choice(DEFAULT_FUNCTIONS)
        arg = Individual._random_expr(vars_list, depth + 1)
        if fn in ("ts_corr",):
            arg2 = Individual._random_expr(vars_list, depth + 1)
            period = random.choice([5, 10, 20, 60])
            return f"{fn}({arg}, {arg2}, {period})"
        if fn in ("if_then",):
            cond = Individual._random_expr(vars_list, depth + 1)
            true_val = Individual._random_expr(vars_list, depth + 1)
            return f"{fn}({arg} - {Individual._random_var(vars_list)}, {true_val}, 0)"
        if fn in ("min", "max"):
            arg2 = Individual._random_expr(vars_list, depth + 1)
            return f"{fn}({arg}, {arg2})"
        period = random.choice([2, 5, 10, 20])
        return f"{fn}({arg}, {period})"

    @staticmethod
    def _random_expr(vars_list: list[str], depth: int = 0) -> str:
        if depth > 3:
            return Individual._random_var(vars_list)
        r = random.random()
        if depth >= 3 or r < 0.35:
            return Individual._random_var(vars_list)
        x = Individual._random_expr(vars_list, depth + 1)
        if r < 0.65:
            op = random.choice(["+", "-", "*", "/"])
            y = Individual._random_expr(vars_list, depth + 1)
            return f"({x} {op} {y})"
        return Individual._random_func(vars_list, depth)


# ═══════════════════════════════════════════════════════════════
# 变异 / 交叉算子
# ═══════════════════════════════════════════════════════════════


def mutate(individual: Individual, vars_list: list[str] | None = None,
           mutation_rate: float = 0.3) -> Individual:
    """变异一个个体 — AST 随机替换。

    策略（随机选择一种）:
      1. 替换一个叶子变量
      2. 替换一个二元运算符
      3. 替换一个函数调用
      4. 乘一个常数抖动
    """
    var_pool = vars_list or DEFAULT_VARIABLES
    src = individual.source
    r = random.random()
    try:
        if r < 0.35:
            # 替换一个变量
            old_var = random.choice(var_pool)
            new_var = random.choice([v for v in var_pool if v != old_var])
            src = _replace_word(src, old_var, new_var)
        elif r < 0.55:
            # 替换运算符
            old_op, new_op = random.choice([("+", "-"), ("-", "+"), ("*", "/"), ("/", "*")])
            src = _replace_word(src, old_op, new_op)
        elif r < 0.75:
            # 替换函数
            old_fn = random.choice(DEFAULT_FUNCTIONS)
            new_fn = random.choice([f for f in DEFAULT_FUNCTIONS if f != old_fn])
            src = _replace_word(src, old_fn, new_fn)
        else:
            # 加微小扰动: expr + const * small_var
            small_var = random.choice(var_pool)
            const = round(random.uniform(-0.01, 0.01), 4)
            src = f"({src} + {const} * {small_var})"
    except Exception:
        pass
    return Individual(source=src, name=f"ga_{_make_name(src)}")


def crossover(parent_a: Individual, parent_b: Individual) -> Individual:
    """子树交叉: 随机选 parent_a 中一个子树，替换 parent_b 中的对应位置。"""
    src = parent_b.source
    try:
        # 简单实现: 交换随机符号
        parts_a = parent_a.source.replace("(", " ( ").replace(")", " ) ").split()
        parts_b = parent_b.source.replace("(", " ( ").replace(")", " ) ").split()
        if len(parts_a) > 4 and len(parts_b) > 4:
            i = random.randint(0, min(len(parts_a), len(parts_b)) - 1)
            parts_b[i] = parts_a[i]
            src = " ".join(parts_b)
    except Exception:
        pass
    return Individual(source=src, name=f"ga_{_make_name(src)}")


def _make_name(src: str) -> str:
    """从 source 生成简短名称。"""
    return src.replace(" ", "").replace("(", "_").replace(")", "").replace(",", "_")[:40]


def _replace_word(text: str, old: str, new: str) -> str:
    """单词边界替换（避免替换子串）。"""
    return re.sub(rf"\b{re.escape(old)}\b", new, text)


import re


# ═══════════════════════════════════════════════════════════════
# FactorMiner — 进化引擎
# ═══════════════════════════════════════════════════════════════


class FactorMiner:
    """基于遗传算法的因子自动挖掘器。

    每代流程:
      变异父代 → 评估 IC → 选择 top_k → 交叉补充 → 下一轮
    """

    def __init__(
        self,
        factor_df: pd.DataFrame,
        forward_returns: pd.Series,
        variable_pool: list[str] | None = None,
    ):
        """
        Args:
            factor_df: 因子/指标 DataFrame（index=code, columns=因子+ 变量）
            forward_returns: 前向收益 Series（index=code）
            variable_pool: 可用于构造表达式的变量名列
        """
        self.factor_df = factor_df
        self.forward_returns = forward_returns
        self.variable_pool = variable_pool or [
            c for c in factor_df.columns
            if c not in ("code", "date", "trade_date", "ts_code", "__index__")
        ]

        # align
        common_idx = factor_df.index.intersection(forward_returns.index)
        self.factor_df = factor_df.loc[common_idx]
        self.forward_returns = forward_returns.loc[common_idx]

        self.history: list[dict[str, Any]] = []

    # ── fitness ─────────────────────────────────────────────

    def _fitness(self, individual: Individual) -> float:
        """评估适应度 = |IC| (信息系数绝对值)。"""
        try:
            val = individual.evaluate(self.factor_df)
            valid = pd.DataFrame({"factor": val, "ret": self.forward_returns}).dropna()
            if len(valid) < 100:
                return 0.0
            ic = valid["factor"].corr(valid["ret"])
            return abs(ic) if np.isfinite(ic) else 0.0
        except Exception:
            return 0.0

    def _evaluate_population(self, pop: list[Individual]) -> list[Individual]:
        """评估种群中所有个体的 fitness。"""
        for ind in pop:
            ind.fitness = self._fitness(ind)
        return sorted(pop, key=lambda x: x.fitness or 0.0, reverse=True)

    # ── evolution ───────────────────────────────────────────

    def evolve(
        self,
        generations: int = 10,
        population_size: int = 30,
        elite_size: int = 5,
        mutation_rate: float = 0.3,
        crossover_rate: float = 0.5,
        min_variables: int = 2,
        verbose: bool = True,
    ) -> list[Individual]:
        """运行遗传算法进化。

        Args:
            generations: 迭代代数
            population_size: 每代种群大小
            elite_size: 保留精英数量
            mutation_rate: 变异概率
            crossover_rate: 交叉概率
            min_variables: 表达式最少引用变量数

        Returns:
            按 fitness 排序的所有已评估个体（去重）
        """
        # 初始化种群 — 用多样性策略生成
        population: list[Individual] = []
        attempts = 0
        while len(population) < population_size and attempts < population_size * 5:
            attempts += 1
            ind = Individual.random()
            vars_used = FactorExpr(ind.source).variables()
            if len(vars_used) >= min_variables:
                # 去重
                if not any(i.source == ind.source for i in population):
                    population.append(ind)

        logger.info(f"初始种群: {len(population)} individuals")

        for gen in range(generations):
            # 评估
            population = self._evaluate_population(population)
            best = population[0]
            avg_fit = np.mean([(i.fitness or 0) for i in population])
            logger.info(
                f"Gen {gen + 1}/{generations}: "
                f"best_fit={best.fitness:.4f} "
                f"avg_fit={avg_fit:.4f} "
                f"best={best.source[:60]}"
            )

            if verbose:
                top5 = population[:5]
                for i, ind in enumerate(top5):
                    print(f"  {i + 1}. [{ind.fitness:.4f}] {ind.source[:80]}")

            # 精英保留
            new_pop = population[:elite_size]

            # 填充新种群
            while len(new_pop) < population_size:
                if random.random() < crossover_rate and len(population) >= 2:
                    p1, p2 = random.sample(population[:population_size // 2], 2)
                    child = crossover(p1, p2)
                else:
                    parent = random.choice(population[:population_size // 2])
                    child = mutate(parent, self.variable_pool, mutation_rate)

                # 验证
                try:
                    vars_used = FactorExpr(child.source).variables()
                    if len(vars_used) >= min_variables and len(vars_used) <= 8:
                        if not any(i.source == child.source for i in new_pop):
                            new_pop.append(child)
                except Exception:
                    continue

            population = new_pop
            self.history.append({"gen": gen + 1, "best_fit": best.fitness, "best": best.source})

        # 最终排序
        population = self._evaluate_population(population)
        return population

    def top_expressions(self, n: int = 10) -> list[FactorExpr]:
        """返回 Top N 因子表达式（可注册并入库）。"""
        pop = self._evaluate_population(
            [Individual.from_source(h["best"]) for h in self.history[-10:]]
        )
        top = pop[:n]
        result = []
        for ind in top:
            fe = FactorExpr(ind.source, name=ind.name or f"ga_{_make_name(ind.source)}")
            result.append(fe)
        return result
