from aiogram.fsm.state import State, StatesGroup

class CreateVideo(StatesGroup):
    waiting_audio = State()
    ratio = State()
    style = State()
    model = State()
    confirm = State()
