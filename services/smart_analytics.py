"""Real persisted analytics scoped to the authenticated user."""
from __future__ import annotations
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from database.models import SignalReceipt, Trade, User

class SmartAnalyticsService:
    def __init__(self, db): self.db = db

    def summary(self, telegram_id: int, period: str = "30d", symbol: str | None = None, direction: str | None = None, status: str | None = None, rejection_reason: str | None = None):
        user = self.db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user: return {"has_data": False, "message": "Analytics unavailable", "metrics": {}}
        cutoff = None if period == "all" else datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) if period == "today" else datetime.utcnow() - timedelta(days=int(period.rstrip("d")))
        sq = self.db.query(SignalReceipt).filter(SignalReceipt.user_id == user.id)
        if cutoff: sq = sq.filter(SignalReceipt.created_at >= cutoff)
        if symbol: sq = sq.filter(SignalReceipt.signal_text.ilike(f"%{symbol.upper()}%"))
        if direction: sq = sq.filter(SignalReceipt.direction == direction.upper())
        if status: sq = sq.filter(SignalReceipt.status == status)
        if rejection_reason: sq = sq.filter(SignalReceipt.rejection_reason.ilike(f"%{rejection_reason}%"))
        signals = sq.order_by(SignalReceipt.created_at.asc()).all()
        tq = self.db.query(Trade).filter(Trade.user_id == user.id)
        if cutoff: tq = tq.filter(Trade.created_at >= cutoff)
        if symbol: tq = tq.filter(Trade.symbol == symbol.upper())
        if direction: tq = tq.filter(Trade.order_type == direction.upper())
        trades = tq.all()
        closed = [t for t in trades if t.closed_at is not None and t.profit_loss is not None]
        values = [float(t.profit_loss) for t in closed]
        accepted = sum(1 for s in signals if s.final_decision in {"accepted", "executed"} or s.status in {"execution", "executed", "dry_run", "partial", "pending", "unknown"})
        rejected = len(signals) - accepted
        daily = defaultdict(float)
        for t in closed: daily[t.closed_at.date().isoformat()] += float(t.profit_loss)
        rejection_counts = Counter((s.rejection_reason or s.status or "Decision unavailable") for s in signals if s.final_decision == "rejected" or s.status not in {"execution", "executed", "dry_run", "partial", "pending", "unknown"})
        latency = [s.execution_latency_ms for s in signals if s.execution_latency_ms is not None]
        return {"period": period, "has_data": bool(signals or trades), "message": None if signals or trades else "No analytics data for the selected period.", "metrics": {"total_signals": len(signals), "accepted_signals": accepted, "rejected_signals": rejected, "executed_trades": sum(t.status in {"executed", "partial", "closed"} for t in trades), "failed_executions": sum(t.status == "failed" for t in trades), "unknown_executions": sum(t.status == "unknown" for t in trades), "winning_trades": sum(v > 0 for v in values), "losing_trades": sum(v < 0 for v in values), "win_rate": round(sum(v > 0 for v in values) / len(values) * 100, 2) if values else None, "total_pnl": round(sum(values), 2) if values else None, "average_pnl": round(sum(values) / len(values), 2) if values else None, "average_execution_latency_ms": round(sum(latency) / len(latency), 3) if latency else None, "signal_to_trade_conversion": round(accepted / len(signals) * 100, 2) if signals else None, "news_protected_signals": sum(s.news_status in {"active", "stale", "unavailable"} for s in signals)}, "rejection_categories": dict(rejection_counts), "daily_pnl": dict(daily), "symbols": dict(Counter(t.symbol for t in trades))}
