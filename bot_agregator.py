from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

import sqlite3

API_TOKEN = 'TOKEN'
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

connection = sqlite3.connect('questions.db')
cursor = connection.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS answers
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 question_id INTEGER,
                 username TEXT,
                 answer TEXT,
                 likes INTEGER DEFAULT 0,
                 FOREIGN KEY(question_id) REFERENCES questions(id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS questions
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 question TEXT,
                 username TEXT,
                 likes INTEGER DEFAULT 0)''')

connection.commit()


class States(StatesGroup):
    WAITING_FOR_QUESTION = State()
    WAITING_FOR_ANSWER = State()
    VIEWING_QUESTIONS = State()
    WAITING_FOR_EDITED_QUESTION = State()
    WAITING_FOR_EDITED_ANSWER = State()
async def save_answer(message: types.Message, question_number):
    username = message.from_user.username
    answer = message.text

    cursor.execute("INSERT INTO answers (question_id, username, answer) VALUES (?, ?, ?)",
                   (question_number, username, answer))

    connection.commit()
    await message.answer(f"Ваш ответ сохранен.")



@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("Задать вопрос")
    item2 = types.KeyboardButton("Мои вопросы")
    item4 = types.KeyboardButton("Мои ответы")
    item3 = types.KeyboardButton("Просмотреть все вопросы")
    markup.add(item1, item2, item3, item4)

    await message.reply("Выберите действие:", reply_markup=markup)


@dp.message_handler(lambda message: message.text == "Задать вопрос")
async def ask_question(message: types.Message):
    await message.answer("Введите свой вопрос:")
    await States.WAITING_FOR_QUESTION.set()


@dp.message_handler(state=States.WAITING_FOR_QUESTION)
async def save_question(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['question'] = message.text

    username = message.from_user.username
    question = message.text
    cursor.execute("INSERT OR REPLACE INTO questions (question, username) VALUES (?, ?)", (question, username))
    connection.commit()
    await message.answer("Спасибо! Ваш вопрос добавлен.")
    await state.finish()


@dp.message_handler(lambda message: message.text == 'Просмотреть все вопросы')
async def show_questions(message: types.Message):
    cursor.execute(
        "SELECT questions.id, questions.username, questions.question, questions.likes, answers.username AS answer_username, answers.answer, answers.id, COUNT(answers.likes) AS answer_likes FROM questions LEFT JOIN answers ON questions.id = answers.question_id GROUP BY answers.id"
    )
    question_answers = cursor.fetchall()

    if question_answers:
        await show_next_question(message, 0)
    else:
        await message.answer("Вопросов с ответами пока нет.")

@dp.message_handler(lambda message: message.text == 'Мои вопросы')
async def my_questions(message: types.Message):
    username = message.from_user.username
    cursor.execute(
        "SELECT id, question FROM questions WHERE username = ?",
        (username,)
    )
    user_questions = cursor.fetchall()

    if user_questions:
        await message.answer("Ваши вопросы:")
        for question in user_questions:
            question_id, question_text = question
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Редактировать", callback_data=f"edit_question_{question_id}"))
            await message.answer(f"{question_text}", reply_markup=markup)
    else:
        await message.answer("У вас пока нет вопросов.")

@dp.callback_query_handler(lambda query: query.data.startswith('edit_question_'))
async def edit_question_callback(query: types.CallbackQuery, state: FSMContext):
    question_id = int(query.data.split('_')[2])
    await query.message.answer("Введите новый текст для вашего вопроса:")
    await States.WAITING_FOR_EDITED_QUESTION.set()
    async with state.proxy() as data:
        data['question_id'] = question_id


@dp.message_handler(state=States.WAITING_FOR_EDITED_QUESTION)
async def save_edited_question(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        question_id = data['question_id']

    new_question = message.text

    cursor.execute("UPDATE questions SET question = ? WHERE id = ?", (new_question, question_id))
    connection.commit()

    await message.answer("Ваш вопрос успешно отредактирован.")
    await state.finish()


@dp.callback_query_handler(lambda query: query.data.startswith('next_question_'))
async def next_question_callback(query: types.CallbackQuery):
    question_index = int(query.data.split('_')[-1])
    await show_next_question(query.message, question_index)


async def show_next_question(message: types.Message, question_index: int):
    cursor.execute(
        "SELECT questions.id, questions.username AS question_username, questions.question, questions.likes AS question_likes, answers.username AS answer_username, answers.answer, answers.id AS answer_id, IFNULL(MAX(answers.likes), 0) AS answer_likes FROM questions LEFT JOIN answers ON questions.id = answers.question_id WHERE questions.id = ? GROUP BY questions.id, answers.id ORDER BY IFNULL(MAX(answers.likes), 0) DESC",
        (question_index + 1,)
    )
    question_answers = cursor.fetchall()

    if question_answers:
        (
            question_id,
            question_username,
            question_text,
            likes,
            answer_username,
            answer,
            answer_id,
            answer_likes
        ) = question_answers[0]  # Берем первый кортеж, так как каждый кортеж соответствует одному ответу
        await message.answer(
            f"Вопрос от @{question_username}:\n{question_text}\n\nКоличество лайков на вопрос: {likes}\n\nОтветы:"
        )

        for question_answer in question_answers:  # Цикл для вывода всех ответов
            (
                _,
                _,
                _,
                _,
                answer_username,
                answer,
                answer_id,
                answer_likes
            ) = question_answer
            if answer:
                await message.answer(
                    f"@{answer_username}: {answer} ({answer_likes} лайков)"
                )
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton(
                        "Лайк", callback_data=f"like_answer_{answer_id}"
                    )
                )

                await message.answer(
                    "Выберите действие для ответа:", reply_markup=markup
                )

        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "Ответить на вопрос", callback_data=f"answer_{question_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "Поставить лайк вопросу", callback_data=f"like_question_{question_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "Назад", callback_data=f"prev_question_{question_index - 1}"
            ),
            types.InlineKeyboardButton(
                "Далее", callback_data=f"next_question_{question_index + 1}"
            )
        )

        await message.answer("Выберите действие:", reply_markup=markup)
    else:
        await message.answer("Вопросов с ответами пока нет.")

@dp.message_handler(lambda message: message.text == 'Мои ответы')
async def my_answers(message: types.Message):
    username = message.from_user.username
    cursor.execute(
        "SELECT questions.id AS question_id, questions.question, answers.id AS answer_id, answers.answer FROM questions JOIN answers ON questions.id = answers.question_id WHERE (answers.username = ? OR questions.username = ?) AND answers.username = ?",
        (username, username, username)
    )
    user_answers = cursor.fetchall()

    if user_answers:
        await message.answer("Ваши ответы на вопросы:")
        for answer in user_answers:
            question_id, question_text, answer_id, answer_text = answer
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Редактировать", callback_data=f"edit_answer_{answer_id}"))
            await message.answer(f"Вопрос: {question_text}\nОтвет: {answer_text}", reply_markup=markup)
    else:
        await message.answer("У вас пока нет ответов на вопросы.")

@dp.callback_query_handler(lambda query: query.data.startswith('edit_answer_'))
async def edit_answer_callback(query: types.CallbackQuery, state: FSMContext):
    answer_id = int(query.data.split('_')[2])
    await query.message.answer("Введите новый текст ответа:")
    await States.WAITING_FOR_EDITED_ANSWER.set()
    async with state.proxy() as data:
        data['answer_id'] = answer_id


@dp.message_handler(state=States.WAITING_FOR_EDITED_ANSWER)
async def save_edited_answer(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        answer_id = data['answer_id']

    new_answer = message.text

    cursor.execute("UPDATE answers SET answer = ? WHERE id = ?",
                   (new_answer, answer_id))
    connection.commit()

    await message.answer("Ваш ответ успешно отредактирован.")
    await state.finish()


@dp.callback_query_handler(lambda query: query.data.startswith('like_answer_'))
async def like_answer_callback(query: types.CallbackQuery):
    answer_id = int(query.data.split('_')[2])

    cursor.execute("UPDATE answers SET likes = likes + 1 WHERE id = ?", (answer_id,))
    connection.commit()

    await query.message.answer("Ваш лайк учтен.")




@dp.callback_query_handler(lambda query: query.data.startswith('like_question_'))
async def like_question_callback(query: types.CallbackQuery):
    question_id = int(query.data.split('_')[2])

    cursor.execute("UPDATE questions SET likes = likes + 1 WHERE id = ?", (question_id,))
    connection.commit()

    await query.message.answer("Ваш лайк учтен.")


@dp.callback_query_handler(lambda query: query.data.startswith('next_question_'))
async def next_question_callback(query: types.CallbackQuery):
    question_index = int(query.data.split('_')[-1])
    await show_next_question(query.message, question_index)


@dp.callback_query_handler(lambda query: query.data.startswith('prev_question_'))
async def prev_question_callback(query: types.CallbackQuery):
    question_index = int(query.data.split('_')[-1])
    await show_next_question(query.message, question_index)


@dp.callback_query_handler(lambda query: query.data.startswith('answer_'))
async def process_answer_callback(query: types.CallbackQuery, state: FSMContext):
    question_number = int(query.data.split('_')[1])

    await query.message.answer("Введите ваш ответ:")
    await States.WAITING_FOR_ANSWER.set()

    async with state.proxy() as data:
        data['question_number'] = question_number


@dp.message_handler(state=States.WAITING_FOR_ANSWER)
async def save_answer_callback(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        question_number = data['question_number']

    await save_answer(message, question_number)
    await state.finish()


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
