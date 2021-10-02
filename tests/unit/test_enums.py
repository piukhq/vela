from app.enums import CampaignStatuses


def test_campaign_statuses_legal_transitions() -> None:
    assert CampaignStatuses.ACTIVE.is_legal_transition(current_status=CampaignStatuses.DRAFT)
    assert CampaignStatuses.CANCELLED.is_legal_transition(current_status=CampaignStatuses.DRAFT)
    assert CampaignStatuses.ENDED.is_legal_transition(current_status=CampaignStatuses.DRAFT)

    assert CampaignStatuses.CANCELLED.is_legal_transition(current_status=CampaignStatuses.ACTIVE)
    assert CampaignStatuses.ENDED.is_legal_transition(current_status=CampaignStatuses.ACTIVE)


def test_campaign_statuses_illegal_transitions() -> None:
    assert not CampaignStatuses.DRAFT.is_legal_transition(current_status=CampaignStatuses.DRAFT)

    assert not CampaignStatuses.DRAFT.is_legal_transition(current_status=CampaignStatuses.ACTIVE)
    assert not CampaignStatuses.ACTIVE.is_legal_transition(current_status=CampaignStatuses.ACTIVE)

    assert not CampaignStatuses.DRAFT.is_legal_transition(current_status=CampaignStatuses.CANCELLED)
    assert not CampaignStatuses.CANCELLED.is_legal_transition(current_status=CampaignStatuses.CANCELLED)
    assert not CampaignStatuses.ENDED.is_legal_transition(current_status=CampaignStatuses.CANCELLED)
    assert not CampaignStatuses.ACTIVE.is_legal_transition(current_status=CampaignStatuses.CANCELLED)

    assert not CampaignStatuses.DRAFT.is_legal_transition(current_status=CampaignStatuses.ENDED)
    assert not CampaignStatuses.CANCELLED.is_legal_transition(current_status=CampaignStatuses.ENDED)
    assert not CampaignStatuses.ENDED.is_legal_transition(current_status=CampaignStatuses.ENDED)
    assert not CampaignStatuses.ACTIVE.is_legal_transition(current_status=CampaignStatuses.ENDED)
