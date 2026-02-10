package com.gabstra.myworkoutassistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import com.gabstra.myworkoutassistant.data.sendErrorLogsToMobile
import com.google.android.gms.wearable.DataClient
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal class WearErrorLogSyncReceiver(
    private val appContext: Context,
    private val toastContext: Context,
    private val dataClient: DataClient
) : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != MyApplication.ERROR_LOGGED_ACTION) {
            return
        }

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val errorLogs = (appContext as? MyApplication)?.getErrorLogs() ?: emptyList()
                if (errorLogs.isEmpty()) {
                    return@launch
                }

                val success = sendErrorLogsToMobile(dataClient, errorLogs)
                if (!success) {
                    Log.e("WearErrorLogSyncReceiver", "Failed to sync error logs to mobile")
                    return@launch
                }

                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        toastContext,
                        "Synced ${errorLogs.size} error log(s) to mobile",
                        Toast.LENGTH_SHORT
                    ).show()
                }
                (appContext as? MyApplication)?.clearErrorLogs()
            } catch (exception: Exception) {
                Log.e("WearErrorLogSyncReceiver", "Error syncing error logs on error", exception)
            }
        }
    }
}
