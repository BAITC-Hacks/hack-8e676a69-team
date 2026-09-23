# Wind Power Forecasting Frontend

## Русский

Этот frontend является частью hackathon-проекта по кейсу **Agentic AI для прогнозирования выработки ВЭС**. Цель проекта — построить интерфейс для системы, которая прогнозирует почасовую выработку ветроэлектростанции на горизонте 24-48 часов.

Система должна использовать исторические данные работы ВЭС с марта 2023 года по 31 января 2026 года включительно и воспроизвести прогнозирование за тестовый период с 1 февраля 2026 года по 28 февраля 2026 года.

Входные данные включают:

- координаты турбины 1: https://maps.app.goo.gl/iN6svMt69D5qRpFU9
- координаты турбины 2: https://maps.app.goo.gl/8UQMwsYavY6nLvFY8
- статистическое время;
- среднюю скорость ветра, м/с;
- нормализированную активную мощность на стороне линии;
- среднюю температуру окружающей среды, °C.

Планируемый интерфейс:

- карта с отображением ВЭС и отдельных турбин;
- выбор ветровой турбины;
- выбор диапазона дат;
- переключение языков: казахский, русский, английский;
- отображение электростанций на карте;
- визуализация прогнозов и ключевых параметров.

Agentic AI-процесс должен самостоятельно выполнять полный цикл: получение архивных прогнозов погоды из открытых источников, подготовка данных, запуск модели, формирование почасового прогноза, анализ результата и повторный расчет при обновлении входных данных.

Важно: для каждого прогнозного периода используются только те прогнозы погоды, которые были доступны на соответствующий исторический момент, а не фактические погодные значения, ставшие известными позднее.

## Қазақша

Бұл frontend **ЖЭС өндірісін болжауға арналған Agentic AI** хакатон жобасының бөлігі болып табылады. Жобаның мақсаты — жел электр станциясының келесі 24-48 сағаттағы сағаттық электр энергиясын өндіруін болжайтын жүйеге арналған интерфейс жасау.

Жүйе 2023 жылғы наурыздан 2026 жылғы 31 қаңтарға дейінгі тарихи деректерді пайдаланып, 2026 жылғы 1 ақпаннан 28 ақпанға дейінгі тест кезеңі үшін болжау процесін қайта орындауы керек.

Берілетін деректер:

- 1-турбинаның координаттары: https://maps.app.goo.gl/iN6svMt69D5qRpFU9
- 2-турбинаның координаттары: https://maps.app.goo.gl/8UQMwsYavY6nLvFY8
- статистикалық уақыт;
- желдің орташа жылдамдығы, м/с;
- желі жағындағы нормаланған белсенді қуат;
- қоршаған ортаның орташа температурасы, °C.

Жоспарланған интерфейс:

- ЖЭС және турбиналарды картада көрсету;
- жел турбинасын таңдау;
- күндер аралығын таңдау;
- тіл ауыстыру: қазақша, орысша, ағылшынша;
- электр станцияларын картада көрсету;
- болжамдар мен негізгі көрсеткіштерді визуализациялау.

Agentic AI процесі толық циклді өздігінен орындауы тиіс: ашық дереккөздерден тарихи ауа райы болжамдарын алу, деректерді дайындау, модельді іске қосу, сағаттық болжам қалыптастыру, нәтижені талдау және кіріс деректері жаңарған кезде қайта есептеу.

Маңызды: әр болжам кезеңі үшін нақты кейін белгілі болған ауа райы мәндері емес, сол тарихи сәтте қолжетімді болған ауа райы болжамдары ғана қолданылуы керек.

## English

This frontend is part of a hackathon project for the case **Agentic AI for wind power plant generation forecasting**. The goal is to build an interface for a system that forecasts hourly wind power generation over a 24-48 hour horizon.

The system should use historical wind power plant operation data from March 2023 through January 31, 2026 and reproduce forecasting for the test period from February 1, 2026 through February 28, 2026.

Provided data includes:

- turbine 1 coordinates: https://maps.app.goo.gl/iN6svMt69D5qRpFU9
- turbine 2 coordinates: https://maps.app.goo.gl/8UQMwsYavY6nLvFY8
- statistical timestamp;
- average wind speed, m/s;
- normalized active power on the line side;
- average ambient temperature, °C.

Planned interface:

- map with wind power plant and turbine locations;
- wind turbine selector;
- date range inputs;
- language switcher: Kazakh, Russian, English;
- power plants displayed on the map;
- forecast and key metric visualization.

The Agentic AI process should complete the full cycle independently: retrieve archived weather forecasts from open sources, prepare data, run the forecasting model, generate hourly forecasts, analyze results, and recalculate when input data is updated.

Important: each forecast period must use only archived weather forecasts that were available at that historical forecast time, not actual weather values observed later.

## Development

```bash
npm install
npm run dev
```

Production build:

```bash
npm run build
```
