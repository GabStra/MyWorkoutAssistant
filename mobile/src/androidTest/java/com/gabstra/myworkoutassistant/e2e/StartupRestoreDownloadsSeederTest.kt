package com.gabstra.myworkoutassistant.e2e

import android.content.ContentValues
import android.os.Environment
import android.provider.MediaStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.StartupRestoreBackupFixture
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class StartupRestoreDownloadsSeederTest {
    @Test
    fun writeValidManualBackupToDownloads() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val resolver = context.contentResolver
        val backupJson = fromAppBackupToJSONPrettyPrint(StartupRestoreBackupFixture.createBackup())
        val fileName = "${StartupRestoreBackupFixture.BACKUP_FILE_PREFIX}_${System.currentTimeMillis()}.json"
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
            put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
        }

        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("Failed to create $fileName in Downloads.")

        resolver.openOutputStream(uri, "wt")?.use { outputStream ->
            outputStream.write(backupJson.toByteArray())
            outputStream.flush()
        } ?: error("Failed to open output stream for $fileName.")
    }
}
