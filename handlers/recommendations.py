from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import F

recommendations_router = Router()


@recommendations_router.callback_query(F.data  == 'recommendations')
async def recommendations(callback: CallbackQuery, session: AsyncSession):
    await callback.message.answer('Рекомендации')
    await callback.answer()
