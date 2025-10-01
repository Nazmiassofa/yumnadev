from config import API
from qdrant_client import AsyncQdrantClient, models

import google.generativeai as genai
import uuid

QDRANT_COLLECTION = "yumna_memories"
genai.configure(api_key=API.GEMINI_KEY)

qdrant_client = AsyncQdrantClient(
    url=API.QDRANT_URL,
    api_key=API.QDRANT_API_KEY,
    check_compatibility=False
)

async def get_vector(query: str) -> list:
    response = genai.embed_content(
        model="models/text-embedding-004",
        content=query,
        task_type="semantic_similarity"
    )
    return response["embedding"]

async def search_memories(query: str, guild_id: str, limit: int = 2) -> list[str]:
    vector = await get_vector(query)
    result = await qdrant_client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=vector,
        limit=limit,
        with_payload=True,
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="guild_id",
                    match=models.MatchValue(value=guild_id)
                )
            ]
        )
    )

    memories = []
    for hit in result:
        if "info" in hit.payload:
            memories.append(hit.payload["info"])
    return memories

async def store_memory(guild_id: str, information: str):
    await ensure_collection()
    vector = await get_vector(information)
    point = models.PointStruct(
        id=str(uuid.uuid4()),
        vector=vector,
        payload={
            "guild_id": guild_id,
            "info": information
        }
    )
    await qdrant_client.upsert(
        collection_name=QDRANT_COLLECTION,
        points=[point]
    )
    
async def ensure_collection():
    collections = await qdrant_client.get_collections()
    if QDRANT_COLLECTION not in [c.name for c in collections.collections]:
        await qdrant_client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=models.VectorParams(
                size=768,  
                distance=models.Distance.COSINE,
            )
        )
