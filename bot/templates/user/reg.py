from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import StatesGroup, State



class RegState(StatesGroup):
    waiting_for_code = State()
    waiting_for_screenshot = State()
    waiting_for_phone_or_card = State()
    waiting_for_bank = State()
    waiting_for_phone_number = State()
    waiting_for_card_number = State()


class RegCallback(CallbackData, prefix='reg'):
    step: str


start_text = (
    "Привет! Это бот компании Pure. Введите секретный код, указанный на голограмме"
)

code_not_found_text = (
    "Код не найден. Попробуйте снова.\n"
    "Обратите внимание что 0 (цифра) похожа на О (букву). Код вводится английскими буквами. "
    "Если у вас возникли сложности, обратитесь в тех поддержку, мы будем рады Вам помочь."
)

code_found_text = (
    "Поздравляем!\n"
    "Вы выиграли 100 рублей!\n"
    "Для того чтобы получить выигрыш:\n\n"
    "1. Подпишитесь на нашу группу о здоровье и молодости, где мы дарим нашим подписчикам наши новые продукты - @zdorovkakslon\n"
    "2. Оставьте отзыв на продукт."
)

not_subscribed_text = "Вы не подписаны на канал о здоровье @zdorovkakslon"

review_request_text = (
    "Напишите развернутый отзыв ⭐️⭐️⭐️⭐️⭐️ о продукте (качество, аромат, упаковка, результат и тд. Не менее 6 цельных слов. "
    "Отдельное спасибо за отзыв с фото нашего продукта), и пришлите скриншот"
)

screenshot_request_text = "Отправьте, пожалуйста, ваш скриншот"

screenshot_error_text = (
    "Пришлите, пожалуйста, скриншот отзыва. Если у Вас возникли сложности, напишите нам в тех. поддержку, "
    "мы будем рады Вам помочь!"
)

phone_or_card_text = "Укажите номер телефона или номер карты для зачисления выигрыша"

phone_format_text = "Укажите ваш номер телефона в формате +79900000000"

card_format_text = "Укажите ваш номер карты в формате 2222 2222 2222 2222"

bank_request_text = "Укажите название банка."

success_text = (
    "Спасибо за заказ продуктов компании Pure. Ваш выигрыш уже в пути. "
    "Он поступит на указанные реквизиты в течении 3х дней."
)