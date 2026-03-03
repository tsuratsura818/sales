"""LINE通知テストスクリプト"""
import asyncio
import sys
sys.path.insert(0, ".")

from app.services import line_service


async def test_text():
    """テキストメッセージテスト"""
    print("1. テキストメッセージを送信中...")
    await line_service.push_text_message("🎉 LINE連携テスト成功！\n案件モニターが正常に動作しています。")
    print("   → 送信完了！LINEを確認してください。")


async def test_flex():
    """Flex Messageテスト（案件カードのサンプル）"""
    print("2. Flex Message（案件カード）を送信中...")
    msg_id = await line_service.push_job_flex_message(
        job_id=0,
        title="【WordPress】コーポレートサイトのリニューアル",
        platform="crowdworks",
        budget_text="100,000〜200,000円",
        deadline_text="2026/04/15",
        match_score=85,
        match_reason="WordPress制作案件で予算も適正。取り組みやすい",
        job_url="https://crowdworks.jp/public/jobs/0",
    )
    if msg_id:
        print(f"   → 送信完了！(message_id: {msg_id})")
    else:
        print("   → 送信失敗。LINE設定を確認してください。")


async def test_flex_lancers():
    """Lancers版Flex Messageテスト"""
    print("3. Lancers版カードを送信中...")
    msg_id = await line_service.push_job_flex_message(
        job_id=1,
        title="ECサイト（Shopify）の構築・デザイン",
        platform="lancers",
        budget_text="150,000〜300,000円",
        deadline_text="2026/05/01",
        match_score=92,
        match_reason="Shopify構築案件。ECサイト経験が活かせる高マッチ案件",
        job_url="https://www.lancers.jp/work/detail/0",
    )
    if msg_id:
        print(f"   → 送信完了！(message_id: {msg_id})")
    else:
        print("   → 送信失敗。")


async def main():
    print("=" * 50)
    print("LINE通知テスト")
    print("=" * 50)

    await test_text()
    await asyncio.sleep(1)

    await test_flex()
    await asyncio.sleep(1)

    await test_flex_lancers()

    print()
    print("=" * 50)
    print("テスト完了！LINEアプリで3つのメッセージを確認してください。")
    print("・テキストメッセージ")
    print("・CrowdWorks案件カード（オレンジ）")
    print("・Lancers案件カード（ブルー）")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
