from app.collectors.base import BaseCollector, CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.services.instagram_pipeline import InstagramCollectionPipeline


class ApifyCollector(BaseCollector):
    """Apify Instagram 四步采集：Discovery → Hydration → Quality Scoring。"""

    async def collect(self, task: CollectionTask) -> list[CollectedInfluencer]:
        platform = (task.platform or "").lower()
        if platform != "instagram":
            raise NotImplementedError(
                f"Apify 采集器暂仅支持 Instagram，当前平台: {platform}"
            )

        result = await InstagramCollectionPipeline.run(task)
        return result.items
