package com.gabstra.myworkoutassistant.e2e.fixtures

import com.gabstra.myworkoutassistant.shared.AppDatabase

object WearFixtureDatabaseSeeder {
    suspend fun resetResumeScenarioTables(db: AppDatabase) {
        db.restHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.workoutHistoryDao().deleteAll()
    }
}
