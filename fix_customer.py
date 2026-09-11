import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect(
        "postgresql://neondb_owner:npg_4uMyoXj8lwBz@ep-holy-bar-aygkg4zi-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require"
    )
    await conn.execute(
        "UPDATE subscriptions SET stripe_customer_id = NULL, stripe_subscription_id = NULL, status = 'free', plan = 'free' WHERE stripe_customer_id = 'cus_test456' OR stripe_customer_id LIKE 'cus_test%' OR stripe_customer_id LIKE 'sub_test%' AND stripe_customer_id LIKE 'cus_%'"
    )
    rows = await conn.fetch(
        "SELECT id, plan, status, stripe_customer_id, stripe_subscription_id FROM subscriptions"
    )
    for r in rows:
        print(dict(r))
    await conn.close()


asyncio.run(main())