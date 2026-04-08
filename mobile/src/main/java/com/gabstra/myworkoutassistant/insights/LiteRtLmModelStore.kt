package com.gabstra.myworkoutassistant.insights

import android.content.Context
import android.net.Uri
import androidx.core.content.edit
import androidx.documentfile.provider.DocumentFile
import java.io.File

private const val INSIGHTS_PREFS = "litert_lm_insights"
private const val MODEL_PATH_KEY = "model_path"

object LiteRtLmModelStore {
    private const val MODEL_DIRECTORY = "litertlm"
    private const val ACTIVE_MODEL_FILE_NAME = "active-model.litertlm"

    fun getConfiguredModelPath(context: Context): String? {
        val path = context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE)
            .getString(MODEL_PATH_KEY, null)
            ?: return null
        return path.takeIf { File(it).isFile() }
    }

    fun clearConfiguredModel(context: Context) {
        context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE).edit {
            remove(MODEL_PATH_KEY)
        }
    }

    fun importModel(context: Context, uri: Uri): String {
        val document = DocumentFile.fromSingleUri(context, uri)
        val sourceName = document?.name ?: ACTIVE_MODEL_FILE_NAME
        require(sourceName.endsWith(".litertlm", ignoreCase = true)) {
            "Select a .litertlm model file."
        }

        val modelDirectory = File(context.filesDir, MODEL_DIRECTORY).apply { mkdirs() }
        val targetFile = File(modelDirectory, ACTIVE_MODEL_FILE_NAME)
        context.contentResolver.openInputStream(uri)?.use { input ->
            targetFile.outputStream().use { output ->
                input.copyTo(output)
            }
        } ?: error("Unable to read the selected model file.")

        context.getSharedPreferences(INSIGHTS_PREFS, Context.MODE_PRIVATE).edit {
            putString(MODEL_PATH_KEY, targetFile.absolutePath)
        }

        return sourceName
    }
}
