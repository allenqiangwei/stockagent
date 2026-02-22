"""Sync concept board data from AkShare to stock_concepts table."""

import logging
import time
from datetime import datetime

from sqlalchemy.orm import Session

from api.models.stock import StockConcept, BoardSyncLog

logger = logging.getLogger(__name__)


def sync_concept_boards(db: Session, max_boards: int = 50) -> int:
    """Sync top concept boards and their constituent stocks.

    Respects daily limit — only syncs once per day.
    Returns number of records upserted.
    """
    log = db.query(BoardSyncLog).filter(BoardSyncLog.board_type == "concept").first()
    if log and log.last_synced.date() == datetime.now().date():
        logger.info("Concept boards already synced today (%d records)", log.record_count)
        return 0

    from api.utils.network import no_proxy

    total_inserted = 0
    try:
        import akshare as ak

        with no_proxy():
            boards_df = ak.stock_board_concept_name_em()

        if boards_df is None or boards_df.empty:
            logger.warning("No concept boards returned from AkShare")
            return 0

        board_names = boards_df["板块名称"].tolist()[:max_boards]
        logger.info("Syncing %d concept boards...", len(board_names))

        for i, board_name in enumerate(board_names):
            try:
                with no_proxy():
                    cons_df = ak.stock_board_concept_cons_em(symbol=board_name)
                time.sleep(0.3)

                if cons_df is None or cons_df.empty:
                    continue

                for _, row in cons_df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if not code or len(code) != 6:
                        continue

                    exists = db.query(StockConcept).filter(
                        StockConcept.stock_code == code,
                        StockConcept.concept_name == board_name,
                    ).first()
                    if not exists:
                        db.add(StockConcept(stock_code=code, concept_name=board_name))
                        total_inserted += 1

                if (i + 1) % 5 == 0:
                    db.commit()
                    logger.info("  synced %d/%d boards (%d records so far)",
                                i + 1, len(board_names), total_inserted)

            except Exception as e:
                logger.warning("Failed to sync board '%s': %s", board_name, e)
                continue

        db.commit()

        if log:
            log.last_synced = datetime.now()
            log.record_count = total_inserted
        else:
            db.add(BoardSyncLog(
                board_type="concept",
                last_synced=datetime.now(),
                record_count=total_inserted,
            ))
        db.commit()

        logger.info("Concept board sync complete: %d new records from %d boards",
                     total_inserted, len(board_names))

    except Exception as e:
        logger.error("Concept board sync failed: %s", e)
        db.rollback()

    return total_inserted
