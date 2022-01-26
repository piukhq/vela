from typing import List

from pydantic import BaseModel, constr

from app.enums import CampaignStatuses


class CampaignsStatusChangeSchema(BaseModel):  # pragma: no cover
    requested_status: CampaignStatuses
    campaign_slugs: List[constr(strip_whitespace=True, min_length=1)]  # type: ignore [valid-type]
