from pydantic import BaseModel, constr

from vela.enums import CampaignStatuses


class ActivityMetadataSchema(BaseModel):
    sso_username: str


class CampaignsStatusChangeSchema(BaseModel):  # pragma: no cover
    requested_status: CampaignStatuses
    campaign_slugs: list[constr(strip_whitespace=True, min_length=1)]  # type: ignore [valid-type]
    issue_pending_rewards: bool | None = False
    activity_metadata: ActivityMetadataSchema
