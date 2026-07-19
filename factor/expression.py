"""因子表达式 DSL — 参考 Qlib / WorldQuant 范式。

以声明式语法描述 alpha 因子，自动求值归因。支持：
  - 基础运算符: + - * / ^
  - 横截面归一化: rank() scale() zscore()
  - 时序算子: ts_mean() ts_std() ts_delta() ts_corr() ts_cross()
  - 逻辑条件: if_then()
  - 表达式合法性校验 + 自动别名

示例:
    expr = Expr("ts_delta(close, 2) / close")
    result = expr.eval(dataframe)

内部表示：
  解析为 AST → 懒求值 → 输出 pd.Series
"""

from __future__ import annotations

import operator
import re
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════
# AST 节点定义
# ═══════════════════════════════════════════════════════════════


class ExprNode(ABC):
    """AST 基类。"""

    def eval(self, scope: dict[str, pd.Series]) -> pd.Series:
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__}>"


@dataclass
class VarNode(ExprNode):
    """变量引用: close, open, vol, ..."""

    name: str

    def eval(self, scope):
        s = scope.get(self.name)
        if s is None:
            raise KeyError(f"Variable '{self.name}' not in scope")
        return s

    def __repr__(self):
        return self.name


@dataclass
class ConstNode(ExprNode):
    """字面常量。"""

    value: float

    def eval(self, scope):
        return pd.Series(self.value, index=scope.get("__index__", None))


@dataclass
class BinaryOp(ExprNode):
    """二元运算 a op b。"""

    left: ExprNode
    right: ExprNode
    op: Callable

    def eval(self, scope):
        return self.op(self.left.eval(scope), self.right.eval(scope))

    def __repr__(self):
        return f"({self.left!r} {_op_repr(self.op)} {self.right!r})"


@dataclass
class UnaryOp(ExprNode):
    """一元运算 op(x)。"""

    operand: ExprNode
    op: Callable

    def eval(self, scope):
        return self.op(self.operand.eval(scope))


@dataclass
class FuncCall(ExprNode):
    """函数调用: func(args...)。"""

    name: str
    args: list[ExprNode]
    kwargs: dict[str, Any] = field(default_factory=dict)

    def eval(self, scope):
        fn = _builtins.get(self.name)
        if fn is None:
            raise NameError(f"Unknown function: {self.name}")
        evaluated = [a.eval(scope) for a in self.args]
        return fn(evaluated, self.kwargs, scope)

    def __repr__(self):
        a = ", ".join(repr(x) for x in self.args)
        return f"{self.name}({a})"


# ═══════════════════════════════════════════════════════════════
# 内置函数
# ═══════════════════════════════════════════════════════════════


def _fn_ts_mean(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    period = int(args[1].iloc[0]) if len(args) > 1 else kw.get("period", 5)
    return args[0].rolling(window=period, min_periods=period).mean()


def _fn_ts_std(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    period = int(args[1].iloc[0]) if len(args) > 1 else kw.get("period", 5)
    return args[0].rolling(window=period, min_periods=period).std()


def _fn_ts_delta(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    period = int(args[1].iloc[0]) if len(args) > 1 else kw.get("period", 1)
    return args[0] - args[0].shift(period)


def _fn_ts_pct(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    period = int(args[1].iloc[0]) if len(args) > 1 else kw.get("period", 1)
    return args[0] / args[0].shift(period) - 1


def _fn_ts_corr(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    period = int(args[2].iloc[0]) if len(args) > 2 else kw.get("period", 20)
    return args[0].rolling(window=period, min_periods=period).corr(args[1])


def _fn_ts_cross(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    """时序交叉: current - mean(s, window)"""
    period = int(args[1].iloc[0]) if len(args) > 1 else kw.get("period", 20)
    m = args[0].rolling(window=period, min_periods=period).mean()
    return args[0] - m


def _fn_rank(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    s = args[0]
    return s.rank(pct=True)


def _fn_zscore(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    s = args[0]
    m, std = s.mean(), s.std()
    denom = std if std != 0 else 1e-9
    return (s - m) / denom


def _fn_scale(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    """横截面 min-max 归一化。"""
    s = args[0]
    mn, mx = s.min(), s.max()
    rng = mx - mn
    denom = rng if rng != 0 else 1e-9
    return (s - mn) / denom


def _fn_if_then(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    """条件: if_then(condition > 0, true_val, false_val)。"""
    cond, t_val, f_val = args[0], args[1], args[2] if len(args) > 2 else pd.Series(0, index=args[0].index)
    return pd.Series(np.where(cond > 0, t_val.values, f_val.values), index=cond.index)


def _fn_sign(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    return np.sign(args[0])


def _fn_abs(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    return args[0].abs()


def _fn_min(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    return pd.Series(np.minimum(args[0].values, args[1].values if len(args) > 1 else args[0].values), index=args[0].index)


def _fn_max(args: list[pd.Series], kw: dict, scope: dict) -> pd.Series:
    return pd.Series(np.maximum(args[0].values, args[1].values if len(args) > 1 else args[0].values), index=args[0].index)


_builtins: dict[str, Callable] = {
    "ts_mean": _fn_ts_mean,
    "ts_std": _fn_ts_std,
    "ts_delta": _fn_ts_delta,
    "ts_pct": _fn_ts_pct,
    "ts_corr": _fn_ts_corr,
    "ts_cross": _fn_ts_cross,
    "rank": _fn_rank,
    "zscore": _fn_zscore,
    "scale": _fn_scale,
    "if_then": _fn_if_then,
    "sign": _fn_sign,
    "abs": _fn_abs,
    "min": _fn_min,
    "max": _fn_max,
}


def _op_repr(op_fn: Callable) -> str:
    mapping = {
        operator.add: "+", operator.sub: "-",
        operator.mul: "*", operator.truediv: "/",
        operator.pow: "^", operator.neg: "-",
    }
    return mapping.get(op_fn, str(op_fn.__name__))


# ═══════════════════════════════════════════════════════════════
# 表达式 Parser — 字符串 → AST
# ═══════════════════════════════════════════════════════════════

_TOKEN = re.compile(r"""
    \s* (
        [+\-*/^()]   |             # operators & parens
        \d+\.?\d*    |             # numeric constant
        [A-Za-z_]\w* |             # identifiers
        [,\[\]]                   # separators
    ) \s*
""", re.VERBOSE)


def parse_expr(source: str) -> ExprNode:
    """Parse a factor expression string into AST."""
    tokens = [t for t in _TOKEN.findall(source) if t.strip()]
    pos = [0]

    def peek() -> str | None:
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def consume() -> str:
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_atom() -> ExprNode:
        t = peek()
        if t is None:
            raise SyntaxError("Unexpected end of expression")
        if re.match(r"^\d+\.?\d*$", t):
            consume()
            return ConstNode(float(t))
        if re.match(r"^[A-Za-z_]\w*$", t):
            name = consume()
            # function call?
            if peek() == "(":
                consume()  # '('
                fargs: list[ExprNode] = []
                while peek() and peek() != ")":
                    fargs.append(parse_expr_term())
                    if peek() == ",":
                        consume()
                if peek() != ")":
                    raise SyntaxError(f"Missing ')' after args of {name}")
                consume()  # ')'
                return FuncCall(name, fargs)
            return VarNode(name)
        if t == "(":
            consume()  # '('
            node = parse_expr_term()
            if peek() != ")":
                raise SyntaxError("Missing ')'")
            consume()
            return node
        if t == "-":
            consume()
            return UnaryOp(parse_atom(), operator.neg)
        raise SyntaxError(f"Unexpected token: {t}")

    def parse_binary(prec: int = 0) -> ExprNode:
        precedence = {operator.add: 1, operator.sub: 1,
                      operator.mul: 2, operator.truediv: 2,
                      operator.pow: 3}
        op_map = {"+": operator.add, "-": operator.sub,
                  "*": operator.mul, "/": operator.truediv, "^": operator.pow}
        left = parse_atom()
        while True:
            t = peek()
            if t is None or t not in op_map:
                break
            op_fn = op_map[t]
            p = precedence.get(op_fn, 0)
            if p <= prec:
                break
            consume()
            right = parse_binary(p)
            left = BinaryOp(left, right, op_fn)
        return left

    def parse_expr_term() -> ExprNode:
        return parse_binary(0)

    return parse_expr_term()


# ═══════════════════════════════════════════════════════════════
# 表达式封装
# ═══════════════════════════════════════════════════════════════


@dataclass
class FactorExpr:
    """可用于注册 + 求值的因子表达式。

    Usage:
        fe = FactorExpr("ts_delta(close, 2) / close", name="delta_2d")
        fe.register()
        df = fe.eval(dataframe)
    """

    source: str
    name: str = ""
    category: str = "technical"
    description: str = ""
    _ast: ExprNode | None = field(default=None, repr=False)

    def __post_init__(self):
        self._ast = parse_expr(self.source)
        if not self.name:
            self.name = self.source

    @property
    def ast(self) -> ExprNode:
        if self._ast is None:
            self._ast = parse_expr(self.source)
        return self._ast

    def eval(self, df: pd.DataFrame) -> pd.Series:
        """评估表达式在给定 DataFrame 上的值。

        Scope 变量从 DataFrame 列名映射。
        """
        scope: dict[str, pd.Series] = {}
        index = df.index
        scope["__index__"] = index
        for col in df.columns:
            scope[str(col)] = df[col]
        result = self.ast.eval(scope)
        result.index = index
        return result

    def register(self) -> None:
        """注册到 FactorRegistry。"""
        from factor.registry import FactorRegistry
        reg = FactorRegistry()
        reg.register(self.name, self.category, self.description or self.source)
        reg.set_factor(self.name, self)

    def variables(self) -> set[str]:
        """返回表达式引用的所有原始变量名。"""
        return _collect_vars(self.ast)


def _collect_vars(node: ExprNode) -> set[str]:
    if isinstance(node, VarNode):
        return {node.name}
    if isinstance(node, BinaryOp):
        return _collect_vars(node.left) | _collect_vars(node.right)
    if isinstance(node, UnaryOp):
        return _collect_vars(node.operand)
    if isinstance(node, FuncCall):
        out: set[str] = set()
        for a in node.args:
            out |= _collect_vars(a)
        return out
    if isinstance(node, ConstNode):
        return set()
    return set()
