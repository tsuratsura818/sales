import asyncio
from datetime import datetime


def _send_email_sync(to: str, subject: str, body: str) -> str:
    """pywin32でOutlookメールを送信する（同期処理）"""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem
        mail.To = to
        mail.Subject = subject
        mail.Body = body
        mail.Send()
        # EntryID取得（送信後すぐは取れない場合があるので空文字も許容）
        return getattr(mail, "EntryID", "") or ""
    except Exception as e:
        raise RuntimeError(f"Outlook送信エラー: {e}")


async def send_email(to: str, subject: str, body: str) -> str:
    """非同期でOutlookメール送信を実行する"""
    loop = asyncio.get_event_loop()
    entry_id = await loop.run_in_executor(None, _send_email_sync, to, subject, body)
    return entry_id
