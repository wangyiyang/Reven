"""Explicit allowlist, write policy and minimum human approval policy."""

from reven.agent.tool_definition import ToolSpec
from reven.agent.tools_crm_contacts import CrmContactTools
from reven.agent.tools_crm_customers import CrmCustomerTools
from reven.agent.tools_crm_follow_ups import CrmFollowUpTools
from reven.agent.tools_rss import RssKeywordTools
from reven.agent.tools_talents_educations import TalentsEducationTools
from reven.agent.tools_talents_experiences import TalentsExperienceTools
from reven.agent.tools_talents_interactions import TalentsInteractionTools
from reven.agent.tools_talents_talents import TalentsTalentTools

TOOL_SPECS = (
    ToolSpec("rss_keyword_create", RssKeywordTools, "create_keyword", is_write=True, refresh_embedding=True),
    ToolSpec("rss_keyword_list", RssKeywordTools, "list_keywords"),
    ToolSpec("rss_keyword_update", RssKeywordTools, "update_keyword", is_write=True, refresh_embedding=True),
    ToolSpec("rss_keyword_delete", RssKeywordTools, "delete_keyword", is_write=True, requires_confirmation=True),
    ToolSpec("crm_customer_list", CrmCustomerTools, "list_customers"),
    ToolSpec("crm_customer_get", CrmCustomerTools, "get_customer"),
    ToolSpec("crm_customer_create", CrmCustomerTools, "create_customer", is_write=True),
    ToolSpec("crm_customer_update", CrmCustomerTools, "update_customer", is_write=True),
    ToolSpec("crm_customer_delete", CrmCustomerTools, "delete_customer", is_write=True, requires_confirmation=True),
    ToolSpec("crm_contact_list", CrmContactTools, "list_contacts"),
    ToolSpec("crm_contact_create", CrmContactTools, "create_contact", is_write=True),
    ToolSpec("crm_contact_update", CrmContactTools, "update_contact", is_write=True),
    ToolSpec("crm_contact_delete", CrmContactTools, "delete_contact", is_write=True, requires_confirmation=True),
    ToolSpec("crm_follow_up_list", CrmFollowUpTools, "list_follow_ups"),
    ToolSpec("crm_follow_up_create", CrmFollowUpTools, "create_follow_up", is_write=True),
    ToolSpec("crm_follow_up_update", CrmFollowUpTools, "update_follow_up", is_write=True),
    ToolSpec("crm_follow_up_delete", CrmFollowUpTools, "delete_follow_up", is_write=True, requires_confirmation=True),
    ToolSpec("crm_lead_funnel", CrmCustomerTools, "lead_funnel_stats"),
    ToolSpec("crm_due_follow_ups", CrmCustomerTools, "list_due_follow_ups"),
    ToolSpec("talent_list", TalentsTalentTools, "list_talents"),
    ToolSpec("talent_get", TalentsTalentTools, "get_talent"),
    ToolSpec("talent_create", TalentsTalentTools, "create_talent", is_write=True),
    ToolSpec("talent_update", TalentsTalentTools, "update_talent", is_write=True),
    ToolSpec("talent_delete", TalentsTalentTools, "delete_talent", is_write=True, requires_confirmation=True),
    ToolSpec("talent_interaction_list", TalentsInteractionTools, "list_interactions"),
    ToolSpec("talent_interaction_create", TalentsInteractionTools, "create_interaction", is_write=True),
    ToolSpec("talent_interaction_update", TalentsInteractionTools, "update_interaction", is_write=True),
    ToolSpec(
        "talent_interaction_delete",
        TalentsInteractionTools,
        "delete_interaction",
        is_write=True,
        requires_confirmation=True,
    ),
    ToolSpec("talent_experience_list", TalentsExperienceTools, "list_experiences"),
    ToolSpec("talent_experience_create", TalentsExperienceTools, "create_experience", is_write=True),
    ToolSpec("talent_experience_update", TalentsExperienceTools, "update_experience", is_write=True),
    ToolSpec(
        "talent_experience_delete",
        TalentsExperienceTools,
        "delete_experience",
        is_write=True,
        requires_confirmation=True,
    ),
    ToolSpec("talent_education_list", TalentsEducationTools, "list_educations"),
    ToolSpec("talent_education_create", TalentsEducationTools, "create_education", is_write=True),
    ToolSpec("talent_education_update", TalentsEducationTools, "update_education", is_write=True),
    ToolSpec(
        "talent_education_delete", TalentsEducationTools, "delete_education", is_write=True, requires_confirmation=True
    ),
    ToolSpec("talent_import_profile", TalentsTalentTools, "import_profile", is_write=True),
)
