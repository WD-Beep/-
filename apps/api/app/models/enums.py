import enum


class CollectionTaskStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_RESULTS = "completed_with_results"
    COMPLETED_NO_RESULTS = "completed_no_results"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    PAUSED = "paused"


class ProfileFailureReason(str, enum.Enum):
    PROFILE_NOT_FOUND = "profile_not_found"
    PRIVATE_ACCOUNT = "private_account"
    MISSING_PROFILE_DETAIL = "missing_profile_detail"
    SCRAPER_BLOCKED = "scraper_blocked"
    INVALID_USERNAME = "invalid_username"


class CandidateSourceType(str, enum.Enum):
    KEYWORD_POST_AUTHOR = "keyword_post_author"
    HASHTAG_POST_AUTHOR = "hashtag_post_author"
    COMMENT_AUTHOR = "comment_author"
    INPUT_PROFILE = "input_profile"
    INPUT_POST = "input_post"
    INPUT_REEL = "input_reel"
    RELATED_PROFILE = "related_profile"
    COMPETITOR_PRODUCT_POST_AUTHOR = "competitor_product_post_author"
    INPUT_URL = "input_url"
    LINK_IMPORT = "link_import"
    LINK_SEED_DISCOVERED = "link_seed_discovered"
    SHOPPING_SEED = "shopping_seed"
    UNKNOWN = "unknown"


class CandidateFailureReason(str, enum.Enum):
    PROFILE_FETCH_FAILED = "profile_fetch_failed"
    PRIVATE_ACCOUNT = "private_account"
    DISABLED_OR_DELETED = "disabled_or_deleted"
    INVALID_USERNAME = "invalid_username"
    MISSING_PROFILE_DETAIL = "missing_profile_detail"
    BELOW_MIN_FOLLOWERS = "below_min_followers"
    BELOW_MIN_ENGAGEMENT_RATE = "below_min_engagement_rate"
    ABOVE_MAX_FOLLOWERS = "above_max_followers"
    MISSING_ENGAGEMENT_RATE = "missing_engagement_rate"
    MISSING_EMAIL = "missing_email"
    MISSING_CONTACT = "missing_contact"
    EXCLUDED_KEYWORD = "excluded_keyword"
    DUPLICATE = "duplicate"
    API_FAILED = "api_failed"
    LOW_VALUE_SEED = "low_value_seed"
    NO_SAME_PRODUCT_MATCH = "no_same_product_match"
    UNKNOWN = "unknown"


class CandidateStatus(str, enum.Enum):
    DISCOVERED = "discovered"
    PENDING_PROFILE = "pending_profile"
    PROFILE_FETCHED = "profile_fetched"
    PROFILE_FAILED = "profile_failed"
    FILTERED_OUT = "filtered_out"
    NOT_INSERTED = "not_inserted"
    INSERTED = "inserted"
    DUPLICATE = "duplicate"


class CollectionMode(str, enum.Enum):
    KEYWORD = "keyword"
    URLS = "urls"
    MIXED = "mixed"
    DISCOVERY = "discovery"
    CATEGORY_DISCOVERY = "category_discovery"
    CLUSTERING = "clustering"
    COMMENT_AUTHORS = "comment_authors"
    COMPETITOR_PRODUCT = "competitor_product"
    LINK_IMPORT = "link_import"
    LINK_SEED_DISCOVERY = "link_seed_discovery"


class LinkImportBatchStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EmailLogStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class LeadStatus(str, enum.Enum):
    NEW = "new"
    TO_CONTACT = "to_contact"
    CONTACTED = "contacted"
    REPLIED = "replied"
    INTERESTED = "interested"
    QUOTED = "quoted"
    COOPERATING = "cooperating"
    COOPERATED = "cooperated"
    INVALID = "invalid"
    BLACKLISTED = "blacklisted"


class FollowupActionType(str, enum.Enum):
    NOTE = "note"
    EMAIL_SENT = "email_sent"
    DM_SENT = "dm_sent"
    REPLIED = "replied"
    STATUS_CHANGED = "status_changed"
    QUOTE_SENT = "quote_sent"
    COOPERATION_STARTED = "cooperation_started"
    COOPERATION_DONE = "cooperation_done"
    INVALID_MARKED = "invalid_marked"
    BLACKLISTED = "blacklisted"


class ContactChannel(str, enum.Enum):
    EMAIL = "email"
    INSTAGRAM_DM = "instagram_dm"
    WHATSAPP = "whatsapp"
    WEBSITE_FORM = "website_form"
    OTHER = "other"


class KnowledgeDocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
