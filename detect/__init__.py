"""Pure edit-war detector. No network and no database."""

from detect.engine import WarEngine
from detect.models import IncomingEdit
from detect.scoring import war_score

__all__ = ["IncomingEdit", "WarEngine", "war_score"]
