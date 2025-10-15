export default {
  async fetch(request, env) {
    const BOT_TOKEN = env.BOT_TOKEN;
    const API_URL = `https://api.telegram.org/bot${8162496264:AAEomZ-eUtqf_jESd6VZSpdHBYJsjPgds7o}`;

    // Обрабатываем входящие апдейты
    if (request.method === "POST") {
      const update = await request.json().catch(() => ({}));
      if (!update.message) {
        return new Response("No message", { status: 200 });
      }

      const chatId = update.message.chat.id;
      const text = update.message.text?.trim() || "";

      // Логика команд
      if (text === "/start" || text === "/menu") {
        const reply = `🔮 Добро пожаловать в Tarot Bot!
Выберите тип расклада:
1. Про отношения ❤️
2. Про работу 💼
3. Про деньги 💰

Напиши, например: отношения`;
        await fetch(`${API_URL}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: reply }),
        });
      } else if (/отношен/i.test(text)) {
        const card = getRandomCard();
        const reply = `🃏 Карта для отношений: ${card.name}\n${card.meaning}`;
        await fetch(`${API_URL}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: reply }),
        });
      } else if (/работ/i.test(text)) {
        const card = getRandomCard();
        const reply = `💼 Карта для работы: ${card.name}\n${card.meaning}`;
        await fetch(`${API_URL}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: reply }),
        });
      } else if (/ден/i.test(text)) {
        const card = getRandomCard();
        const reply = `💰 Карта для финансов: ${card.name}\n${card.meaning}`;
        await fetch(`${API_URL}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: reply }),
        });
      } else {
        await fetch(`${API_URL}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: chatId,
            text: "Напиши /menu, чтобы выбрать тип расклада 🔮",
          }),
        });
      }

      return new Response("OK", { status: 200 });
    }

    // GET-запросы → просто показать статус
    return new Response("Tarot Worker active", { status: 200 });
  },
};

// Простая колода прямо в коде
function getRandomCard() {
  const cards = [
    { name: "Шут (0)", meaning: "Начало нового пути, доверие миру." },
    { name: "Императрица (III)", meaning: "Рост, плодородие, изобилие." },
    { name: "Башня (XVI)", meaning: "Внезапные перемены, разрушение иллюзий." },
    { name: "Солнце (XIX)", meaning: "Успех, радость, ясность." },
    { name: "Луна (XVIII)", meaning: "Неопределенность, тайные страхи." },
  ];
  return cards[Math.floor(Math.random() * cards.length)];
}
