"""Real-data results and activity calculations, scoped to one user."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from database.models import SignalReceipt, Trade, User


class ResultsService:
    def __init__(self, db):
        self.db = db

    def _user(self, telegram_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.telegram_id == telegram_id).first()

    @staticmethod
    def _cutoff(period: str) -> Optional[datetime]:
        if period == "today":
            now = datetime.utcnow()
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period in {"7d", "30d"}:
            return datetime.utcnow() - timedelta(days=int(period[:-1]))
        return None

    def results(self, telegram_id: int, period: str = "30d") -> dict[str, Any]:
        user = self._user(telegram_id)
        if not user:
            return {"period": period, "has_data": False, "has_signals": False, "message": "No data for the selected period.", "metrics": {}, "trades": [], "signals": []}
        cutoff = self._cutoff(period)
        query = self.db.query(Trade).filter(Trade.user_id == user.id, Trade.closed_at.isnot(None))
        if cutoff:
            query = query.filter(Trade.closed_at >= cutoff)
        trades = query.order_by(Trade.closed_at.desc()).all()
        signal_query = self.db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id)
        if cutoff:
            signal_query = signal_query.filter(SignalReceipt.created_at >= cutoff)
        signals = signal_query.order_by(SignalReceipt.created_at.desc()).limit(100).all()
        values = [float(t.profit_loss) for t in trades if t.profit_loss is not None]
        wins = [v for v in values if v > 0]
        losses = [v for v in values if v < 0]
        net = sum(values)
        running = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in values[::-1]:
            running += value
            peak = max(peak, running)
            max_drawdown = max(max_drawdown, peak - running)
        return {
            "period": period,
            "has_data": bool(trades),
            "has_signals": bool(signals),
            "message": None if trades or signals else "No data for the selected period.",
            "metrics": {
                "total_closed_trades": len(trades),
                "winning_trades": len(wins),
                "losing_trades": len(losses),
                "win_rate": round(len(wins) / len(values) * 100, 2) if values else None,
                "total_pnl": round(net, 2) if values else None,
                "average_win": round(sum(wins) / len(wins), 2) if wins else None,
                "average_loss": round(sum(losses) / len(losses), 2) if losses else None,
                "best_trade": max(values) if values else None,
                "worst_trade": min(values) if values else None,
                "max_drawdown": round(max_drawdown, 2) if values else None,
            },
            "trades": [{
                "id": t.id, "symbol": t.symbol, "order_type": t.order_type,
                "profit_loss": float(t.profit_loss) if t.profit_loss is not None else None,
                "status": t.status, "closed_at": t.closed_at.isoformat() + "Z" if t.closed_at else None,
            } for t in trades[:50]],
            "signals": [{
                "id": s.id,
                "source": s.source,
                "status": s.status,
                "rejection_reason": s.rejection_reason,
                "news_status": s.news_status,
                "trade_id": s.trade_uuid,
                "created_at": s.created_at.isoformat() + "Z" if s.created_at else None,
            } for s in signals],
        }

    def activity(self, telegram_id: int) -> dict[str, Any]:
        user = self._user(telegram_id)
        if not user:
            return {"has_data": False, "message": "No activity yet."}
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        signals = self.db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id, SignalReceipt.created_at >= start).all()
        trades = self.db.query(Trade).filter(Trade.user_id == user.id, Trade.created_at >= start).all()
        counts = {}
        for receipt in signals:
            counts[receipt.status] = counts.get(receipt.status, 0) + 1
        accepted_statuses = {"approved", "execution", "executed", "dry_run", "partial", "pending", "unknown"}
        rejected = sum(1 for receipt in signals if receipt.status not in accepted_statuses)
        accepted = sum(1 for receipt in signals if receipt.status in accepted_statuses)
        executed = sum(1 for trade in trades if trade.status in {"executed", "partial", "closed"})
        active = sum(1 for trade in trades if trade.closed_at is None and trade.status not in {"failed", "cancelled"})
        pnl = sum(float(t.profit_loss or 0) for t in trades if t.closed_at is not None)
        return {
            "has_data": bool(signals or trades), "date": start.date().isoformat(),
            "signals_received": len(signals), "signals_accepted": accepted,
            "signals_rejected": rejected, "signal_statuses": counts,
            "trades": len(trades), "trades_executed": executed,
            "trades_active": active, "closed": sum(1 for t in trades if t.closed_at is not None),
            "wins": sum(1 for t in trades if t.closed_at is not None and (t.profit_loss or 0) > 0),
            "losses": sum(1 for t in trades if t.closed_at is not None and (t.profit_loss or 0) < 0),
            "pnl": round(pnl, 2),
            "news_blocked": counts.get("news_blocked", 0) + counts.get("news_unavailable", 0) + counts.get("news_stale", 0),
            "risk_blocked": counts.get("risk_blocked", 0),
        }
