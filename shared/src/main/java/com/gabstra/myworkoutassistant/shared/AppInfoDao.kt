package com.gabstra.myworkoutassistant.shared

import androidx.room.*
import java.util.UUID

@Dao
interface AppInfoDao {

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun insert(appInfo: AppInfo)

    @Query("SELECT * FROM app_info WHERE id = 1")
    fun getAppInfo(): AppInfo?

    @Transaction
    fun addEntityToSync(uuid: UUID) {
        val appInfo = getAppInfo() ?: AppInfo(entitiesToSync = emptyList())
        val updatedList = appInfo.entitiesToSync.toMutableList().apply { add(uuid) }
        insert(appInfo.copy(entitiesToSync = updatedList))
    }

    @Transaction
    fun removeEntityToSync(uuid: UUID) {
        val appInfo = getAppInfo() ?: return
        val updatedList = appInfo.entitiesToSync.toMutableList().apply { remove(uuid) }
        insert(appInfo.copy(entitiesToSync = updatedList))
    }
}