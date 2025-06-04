- 👋 Hi, I’m @ChangKeqing
- 👀 I’m interested in System Engineering
- 🌱 I’m currently learning Julia
- 💞️ I’m looking to collaborate on Uncertainty Qualification
- 📫 How to reach me @changkeqing@buaa.edu.cn

<!---
ChangKeqing/ChangKeqing is a ✨ special ✨ repository because its `README.md` (this file) appears on your GitHub profile.
You can click the Preview link to take a look at your changes.
--->

## Android Calendar App

This repository includes a minimal Android calendar application located in the `AndroidCalendarApp` directory. It demonstrates a simple `CalendarView` in `MainActivity`.

### Building

To build the application, open the project in Android Studio or use the Android command-line tools with the Android SDK installed:

```bash
cd AndroidCalendarApp
./gradlew assembleDebug
```

The resulting APK can be found under `app/build/outputs/apk/debug/`.

## Data Visualization Dashboard

The `DataVizDashboard` directory contains a small Flask-based web application that connects to a MySQL database and displays data using Chart.js. It serves as a simple example of a browser/server (B/S) big-screen visualization tool.

```bash
cd DataVizDashboard
pip install -r requirements.txt
python app.py
```

Configure the required MySQL environment variables as described in `DataVizDashboard/README.md` before launching the server.
