"""分钟线更新器。"""
from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date

from config.settings import settings
from data.source.tushare_source import MINUTE_BAR_CHUNK_DAYS, _chunk_date_range
from utils.logger import get_logger

from .base import BaseUpdater

logger = get_logger("minute_bar_updater")
WAIT_HEARTBEAT_SECONDS = 30
MAX_NO_PROGRESS_HEARTBEATS = 6


def _render_pending_chunks(pending_chunks: list[tuple[str, int, int, date, date]]) -> str:
    """Render a compact pending-chunk summary for heartbeat logs."""
    return ", ".join(
        f"{target_code}:{chunk_index}/{total_chunks}({chunk_start}..{chunk_end})"
        for target_code, chunk_index, total_chunks, chunk_start, chunk_end in pending_chunks
    )


def _raise_stall_error(scope: str, pending_summary: str, pending_futures: int) -> None:
    """Raise a timeout with enough context to pinpoint the stuck chunk set."""
    raise TimeoutError(
        f"{scope} stalled after repeated no-progress waits "
        f"pending_futures={pending_futures} pending_chunks=[{pending_summary}]"
    )


class MinuteBarUpdater(BaseUpdater):
    """Refresh minute bars into market storage."""

    source_capability = 'minute_bar'

    def _resolve_target_codes(self, ts_code: str | None, ts_codes: Sequence[str] | None) -> list[str]:
        """Resolve the requested symbol scope for minute-bar loading."""
        if ts_code is not None:
            return [ts_code]

        resolved_codes = self._ensure_code_list(ts_codes)
        if resolved_codes:
            return resolved_codes

        stock_basic = self.source.fetch_stock_basic()
        return [code for code in stock_basic.get('ts_code', []).tolist() if isinstance(code, str) and code]

    @staticmethod
    def _iter_reverse_chunks(start_date: date, end_date: date) -> list[tuple[date, date]]:
        """Return inclusive date chunks ordered from newest to oldest."""
        chunks = _chunk_date_range(start_date, end_date, days=MINUTE_BAR_CHUNK_DAYS)
        return list(reversed(chunks))

    def _run_single_code(
        self,
        target_code: str,
        reverse_chunks: list[tuple[date, date]],
        freq: str,
        max_workers: int,
    ) -> int:
        """Fetch one symbol with chunk-level concurrency and completion-order persistence."""
        total_rows = 0
        next_chunk_offset = 0
        no_progress_waits = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk: dict[object, tuple[int, int, date, date]] = {}

            def submit_next_chunk() -> bool:
                nonlocal next_chunk_offset
                if next_chunk_offset >= len(reverse_chunks):
                    return False
                chunk_start, chunk_end = reverse_chunks[next_chunk_offset]
                future = executor.submit(self.source.fetch_minute_bar, target_code, chunk_start, chunk_end, freq)
                future_to_chunk[future] = (
                    next_chunk_offset + 1,
                    len(reverse_chunks),
                    chunk_start,
                    chunk_end,
                )
                next_chunk_offset += 1
                return True

            while len(future_to_chunk) < max_workers and submit_next_chunk():
                pass

            while future_to_chunk:
                done, _ = wait(
                    tuple(future_to_chunk),
                    timeout=WAIT_HEARTBEAT_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    no_progress_waits += 1
                    pending_summary = _render_pending_chunks(
                        [(target_code, *chunk_meta) for chunk_meta in future_to_chunk.values()]
                    )
                    logger.warning(
                        'minute_bar waiting for remote chunk result '
                        f'ts_code={target_code} pending_futures={len(future_to_chunk)} '
                        f'pending_chunks=[{pending_summary}] no_progress_waits={no_progress_waits}'
                    )
                    if no_progress_waits >= MAX_NO_PROGRESS_HEARTBEATS:
                        _raise_stall_error('minute_bar single-code', pending_summary, len(future_to_chunk))
                    continue

                no_progress_waits = 0
                for future in done:
                    chunk_index, total_chunks, chunk_start, chunk_end = future_to_chunk.pop(future)
                    chunk_rows = self._upsert_market('minute_bar', future.result())
                    total_rows += chunk_rows
                    logger.info(
                        f'minute_bar progress ts_code={target_code} chunk={chunk_index}/{total_chunks} '
                        f'range={chunk_start}..{chunk_end} chunk_rows={chunk_rows} total_rows={total_rows}'
                    )
                    submit_next_chunk()

        return total_rows

    def _run_multi_code(
        self,
        target_codes: list[str],
        reverse_chunks_by_code: dict[str, list[tuple[date, date]]],
        freq: str,
        max_workers: int,
    ) -> int:
        """Fetch multiple symbols with stock-level concurrency while serializing writes."""
        total_rows = 0
        pending_codes = iter(target_codes)
        active_codes: set[str] = set()
        no_progress_waits = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chunk: dict[object, tuple[str, int, int, date, date]] = {}

            def submit_next_chunk(target_code: str) -> bool:
                reverse_chunks = reverse_chunks_by_code[target_code]
                chunk_index = active_code_chunk_offsets[target_code]
                if chunk_index >= len(reverse_chunks):
                    return False
                chunk_start, chunk_end = reverse_chunks[chunk_index]
                future = executor.submit(self.source.fetch_minute_bar, target_code, chunk_start, chunk_end, freq)
                future_to_chunk[future] = (
                    target_code,
                    chunk_index + 1,
                    len(reverse_chunks),
                    chunk_start,
                    chunk_end,
                )
                active_code_chunk_offsets[target_code] = chunk_index + 1
                return True

            def activate_next_code() -> bool:
                for next_code in pending_codes:
                    if next_code in active_codes:
                        continue
                    active_codes.add(next_code)
                    if submit_next_chunk(next_code):
                        return True
                    active_codes.remove(next_code)
                return False

            active_code_chunk_offsets = {target_code: 0 for target_code in target_codes}
            while len(active_codes) < max_workers and activate_next_code():
                pass

            while future_to_chunk:
                done, _ = wait(
                    tuple(future_to_chunk),
                    timeout=WAIT_HEARTBEAT_SECONDS,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    no_progress_waits += 1
                    pending_summary = _render_pending_chunks(list(future_to_chunk.values())[:max_workers])
                    logger.warning(
                        'minute_bar waiting for remote chunk results '
                        f'active_codes={sorted(active_codes)} pending_futures={len(future_to_chunk)} '
                        f'pending_chunks=[{pending_summary}] no_progress_waits={no_progress_waits}'
                    )
                    if no_progress_waits >= MAX_NO_PROGRESS_HEARTBEATS:
                        _raise_stall_error('minute_bar multi-code', pending_summary, len(future_to_chunk))
                    continue

                no_progress_waits = 0
                for future in done:
                    target_code, chunk_index, total_chunks, chunk_start, chunk_end = future_to_chunk.pop(future)
                    chunk_rows = self._upsert_market('minute_bar', future.result())
                    total_rows += chunk_rows
                    logger.info(
                        f'minute_bar progress ts_code={target_code} chunk={chunk_index}/{total_chunks} '
                        f'range={chunk_start}..{chunk_end} chunk_rows={chunk_rows} total_rows={total_rows}'
                    )
                    if not submit_next_chunk(target_code):
                        active_codes.remove(target_code)
                        activate_next_code()

        return total_rows

    def run(
        self,
        ts_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        freq: str = '5min',
        ts_codes: Sequence[str] | None = None,
    ) -> dict[str, int]:
        """Fetch and persist minute bars for one symbol or an expanded universe."""
        if start_date is None or end_date is None:
            raise ValueError('start_date and end_date are required for minute_bar updates')

        target_codes = self._resolve_target_codes(ts_code, ts_codes)
        reverse_chunks_by_code = {
            target_code: self._iter_reverse_chunks(start_date, end_date) for target_code in target_codes
        }
        max_workers = settings.resolved_minute_bar_stock_workers

        if len(target_codes) == 1:
            total_rows = self._run_single_code(
                target_codes[0],
                reverse_chunks_by_code[target_codes[0]],
                freq,
                max_workers,
            )
            return {'minute_bar': total_rows}

        total_rows = self._run_multi_code(target_codes, reverse_chunks_by_code, freq, max_workers)
        return {'minute_bar': total_rows}
