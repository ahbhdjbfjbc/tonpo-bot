"""Deterministic, fail-closed protection checks for the canonical signal pipeline."""
from __future__ import annotations
from datetime import datetime, timezone
import math
from typing import Any
from database.models import AdminSetting, Trade

class ProtectionService:
    def __init__(self, db): self.db = db

    def evaluate_account_limits(self, user, account_info, positions, *, now=None):
        """Evaluate account-wide limits using one authoritative broker snapshot.

        This is deliberately fail-closed: an execution cannot proceed without
        valid equity and a complete position snapshot.
        """
        now = now or datetime.now(timezone.utc)
        account_settings = getattr(user, "settings", None)
        if account_settings is None or not isinstance(account_info, dict) or not isinstance(positions, list):
            return self._blocked("account_snapshot_unavailable", "Account balance, equity, or positions are unavailable")
        try:
            balance = float(account_info["balance"])
            equity = float(account_info["equity"])
            if not all(math.isfinite(value) for value in (balance, equity)) or balance <= 0 or equity <= 0:
                raise ValueError("invalid account values")
            floating = 0.0
            for position in positions:
                if not isinstance(position, dict):
                    raise ValueError("invalid position snapshot")
                raw_profit = position.get("profit", position.get("floating_pnl"))
                if raw_profit is None or not math.isfinite(float(raw_profit)):
                    raise ValueError("position profit is unavailable")
                floating += float(raw_profit)

            day_start = now.astimezone(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )
            realized = sum(
                float(trade.profit_loss)
                for trade in self.db.query(Trade).filter(
                    Trade.user_id == user.id,
                    Trade.closed_at >= day_start,
                    Trade.profit_loss.isnot(None),
                ).all()
            )
            if not all(math.isfinite(value) for value in (realized, floating)):
                raise ValueError("invalid pnl snapshot")

            max_daily_loss = account_settings.max_daily_loss
            if max_daily_loss is not None:
                max_daily_loss = float(max_daily_loss)
                if not math.isfinite(max_daily_loss) or max_daily_loss <= 0:
                    raise ValueError("invalid daily loss limit")
                if realized + floating <= -max_daily_loss:
                    return self._blocked("daily_loss", "Daily realized and floating loss limit reached")

            max_open_positions = account_settings.max_open_positions
            if max_open_positions is not None:
                max_open_positions = int(max_open_positions)
                if max_open_positions <= 0:
                    raise ValueError("invalid open positions limit")
                if len(positions) >= max_open_positions:
                    return self._blocked("max_open_positions", "Maximum open positions reached")

            max_open_trades = account_settings.max_open_trades
            if max_open_trades is not None:
                max_open_trades = int(max_open_trades)
                if max_open_trades <= 0:
                    raise ValueError("invalid open trades limit")
                open_statuses = {"pending", "executing", "executed", "partial", "open"}
                open_trades = self.db.query(Trade).filter(
                    Trade.user_id == user.id,
                    Trade.status.in_(open_statuses),
                ).count()
                if open_trades >= max_open_trades:
                    return self._blocked("max_open_trades", "Maximum open trades reached")

            max_drawdown_pct = account_settings.max_drawdown_pct
            if max_drawdown_pct is not None:
                max_drawdown_pct = float(max_drawdown_pct)
                if not math.isfinite(max_drawdown_pct) or max_drawdown_pct <= 0:
                    raise ValueError("invalid drawdown limit")
                peak = account_settings.peak_equity
                if peak is None:
                    peak = equity
                peak = float(peak)
                if not math.isfinite(peak) or peak <= 0:
                    raise ValueError("invalid peak equity")
                if equity > peak:
                    peak = equity
                    account_settings.peak_equity = peak
                    self.db.commit()
                drawdown_pct = ((peak - equity) / peak) * 100.0
                if drawdown_pct >= max_drawdown_pct:
                    return self._blocked("max_drawdown", "Maximum drawdown limit reached")
            return {"allowed": True, "code": "passed", "reason": "Account risk limits passed"}
        except Exception:
            self.db.rollback()
            return self._blocked("account_snapshot_unavailable", "Account risk data unavailable; execution is blocked")

    def evaluate(self, user, signal, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        account_settings = getattr(user, "settings", None)
        if account_settings is None: return self._blocked("protection_unavailable", "Protection settings are unavailable")
        try:
            stops = self.db.query(AdminSetting).filter(AdminSetting.key.in_(["kill_switch", "emergency_stop"])).all()
            if any(str(item.value).lower() == "true" for item in stops): return self._blocked("kill_switch", "Emergency stop is active")
            if not getattr(account_settings, "protection_enabled", True): return {"allowed": True, "code": "disabled", "reason": "Protection checks are disabled by account configuration"}
            metadata = dict(getattr(signal, "metadata", {}) or {})
            max_spread = getattr(account_settings, "max_spread", None)
            if max_spread is not None:
                bid, ask = metadata.get("bid"), metadata.get("ask")
                if bid is None or ask is None: return self._blocked("spread_unavailable", "Spread data unavailable; protection is fail-closed")
                if abs(float(ask) - float(bid)) > float(max_spread): return self._blocked("spread", "Spread exceeds the configured maximum")
            max_slippage = getattr(account_settings, "max_slippage", None)
            observed_slippage = metadata.get("slippage", metadata.get("observed_slippage"))
            if max_slippage is not None and observed_slippage is not None and float(observed_slippage) > float(max_slippage): return self._blocked("slippage", "Slippage exceeds the configured maximum")
            max_volatility = getattr(account_settings, "max_volatility", None)
            observed_volatility = metadata.get("volatility", metadata.get("observed_volatility"))
            if max_volatility is not None and observed_volatility is not None and float(observed_volatility) > float(max_volatility): return self._blocked("volatility", "Volatility exceeds the configured maximum")
            start, end = getattr(account_settings, "session_start_utc", None), getattr(account_settings, "session_end_utc", None)
            if start and end:
                current = now.astimezone(timezone.utc).strftime("%H:%M")
                inside = (start <= current <= end) if start <= end else (current >= start or current <= end)
                if not inside: return self._blocked("session", "Outside the configured trading session")
            max_daily_loss = getattr(account_settings, "max_daily_loss", None)
            if max_daily_loss is not None:
                day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
                pnl = sum(float(t.profit_loss or 0) for t in self.db.query(Trade).filter(Trade.user_id == user.id, Trade.closed_at >= day_start, Trade.profit_loss.isnot(None)).all())
                if pnl <= -abs(float(max_daily_loss)): return self._blocked("daily_loss", "Daily loss limit reached")
            max_losses = getattr(account_settings, "max_consecutive_losses", None)
            if max_losses is not None:
                rows = self.db.query(Trade).filter(Trade.user_id == user.id, Trade.closed_at.isnot(None), Trade.profit_loss.isnot(None)).order_by(Trade.closed_at.desc()).limit(int(max_losses) + 1).all()
                consecutive = 0
                for trade in rows:
                    if float(trade.profit_loss) < 0: consecutive += 1
                    else: break
                if consecutive >= int(max_losses): return self._blocked("consecutive_loss", "Consecutive loss protection is active")
            return {"allowed": True, "code": "passed", "reason": "Protection checks passed"}
        except Exception:
            self.db.rollback()
            return self._blocked("protection_unavailable", "Protection data unavailable; new execution is blocked")

    @staticmethod
    def _blocked(code, reason): return {"allowed": False, "code": code, "reason": reason}
