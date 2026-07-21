# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：discovery accumulator
"""发现阶段候选累积：保留原始条数并统计去重/重复。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.apify_instagram import PostAuthorCandidate


def _enrich_existing(existing: PostAuthorCandidate, candidate: PostAuthorCandidate) -> None:
    if not existing.source_post_url and candidate.source_post_url:
        existing.source_post_url = candidate.source_post_url
    if not existing.source_comment_text and candidate.source_comment_text:
        existing.source_comment_text = candidate.source_comment_text
    if not existing.source_comment_url and candidate.source_comment_url:
        existing.source_comment_url = candidate.source_comment_url
    if not existing.source_discovery_type and candidate.source_discovery_type:
        existing.source_discovery_type = candidate.source_discovery_type
    if not existing.source_hashtag and candidate.source_hashtag:
        existing.source_hashtag = candidate.source_hashtag
    if not existing.source_caption and candidate.source_caption:
        existing.source_caption = candidate.source_caption
    if not existing.source_meta and candidate.source_meta:
        existing.source_meta = candidate.source_meta


@dataclass
class DiscoveryAccumulator:
    raw_candidates: list[PostAuthorCandidate] = field(default_factory=list)
    deduped_map: dict[str, PostAuthorCandidate] = field(default_factory=dict)
    discovery_duplicates: list[PostAuthorCandidate] = field(default_factory=list)

    def add(self, candidate: PostAuthorCandidate) -> bool:
        """追加原始候选；若 profile_url 已存在则记入 discovery_duplicates。返回 True 表示首次出现。"""
        self.raw_candidates.append(candidate)
        key = candidate.profile_url.lower()
        existing = self.deduped_map.get(key)
        if existing:
            _enrich_existing(existing, candidate)
            self.discovery_duplicates.append(candidate)
            return False
        self.deduped_map[key] = candidate
        return True

    @property
    def deduped_candidates(self) -> list[PostAuthorCandidate]:
        return list(self.deduped_map.values())

    @property
    def duplicate_count(self) -> int:
        return len(self.raw_candidates) - len(self.deduped_map)
