import asyncio
import json
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

from api.database import database_url

async def seed_db(fallback_dir: Path):
    url = database_url()
    if not url:
        print("DATABASE_URL not set. Skipping DB seed.")
        return

    # Convert to async URL if needed
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://")
        
    engine = create_async_engine(url, echo=False)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    files_to_cache = [
        "demo_data.json",
        "clusters.json",
        "hotspots.json",
        "patrol_routes.json",
        "anomalies.json",
        "commander_context.json",
        "map_roads.json",
        "etl_report.json"
    ]

    async with async_session() as session:
        # We will populate the api_cache table first so the serving layer can read from DB
        for filename in files_to_cache:
            file_path = fallback_dir / filename
            if file_path.exists():
                with open(file_path, "r") as f:
                    payload = json.load(f)
                    
                # Upsert into api_cache
                query = text("""
                    INSERT INTO api_cache (cache_key, payload, source, updated_at)
                    VALUES (:cache_key, :payload, 'postgres_seed', now())
                    ON CONFLICT (cache_key) DO UPDATE SET 
                        payload = EXCLUDED.payload,
                        source = EXCLUDED.source,
                        updated_at = EXCLUDED.updated_at
                """)
                await session.execute(query, {
                    "cache_key": filename,
                    "payload": json.dumps(payload)
                })
                print(f"Seeded {filename} into api_cache")
                
        await session.commit()
    await engine.dispose()
    print("Database seeding completed.")

if __name__ == "__main__":
    import sys
    fallback_dir = Path(__file__).parent.parent.parent / "public" / "fallback"
    asyncio.run(seed_db(fallback_dir))
