package com.gabstra.myworkoutassistant

import android.app.Activity
import android.app.Application
import android.content.Intent
import android.os.Bundle
import android.util.Log
import com.gabstra.myworkoutassistant.shared.ErrorLog
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.google.gson.GsonBuilder
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileWriter
import java.io.PrintWriter
import java.io.StringWriter
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.concurrent.atomic.AtomicInteger

class MyApplication : Application() {
    
    private val errorLogFile: File by lazy {
        File(filesDir, "error_logs.json")
    }
    
    private val gson = GsonBuilder()
        .setPrettyPrinting()
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .create()
    
    // Make this accessible so ViewModels can use it
    val coroutineExceptionHandler = CoroutineExceptionHandler { _, throwable ->
        Log.e("MyApplication", "Uncaught exception in coroutine", throwable)
        logErrorToFile("Coroutine", throwable)
    }
    
    override fun onCreate() {
        super.onCreate()

        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityResumed(activity: Activity) {
                resumedActivities.incrementAndGet()
                isInForeground = true
            }

            override fun onActivityPaused(activity: Activity) {
                val remaining = resumedActivities.decrementAndGet()
                if (remaining <= 0) {
                    resumedActivities.set(0)
                    isInForeground = false
                }
            }

            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
            override fun onActivityStarted(activity: Activity) = Unit
            override fun onActivityStopped(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
        
        // Set up global uncaught exception handler
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()
        
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            Log.e("MyApplication", "Uncaught exception in thread: ${thread.name}", throwable)
            
            // Log stack trace for debugging
            throwable.printStackTrace()
            
            // Log error to file
            logErrorToFile(thread.name, throwable)
            
            // Attempt graceful recovery - don't crash immediately
            // In a workout scenario, we want to preserve state if possible
            try {
                // You could save workout state here if needed
                // For now, we'll just log and let the default handler run
            } catch (e: Exception) {
                Log.e("MyApplication", "Error in exception handler", e)
            }
            
            // Call the default handler to handle the crash normally
            // This ensures the app still crashes but we've logged everything
            defaultHandler?.uncaughtException(thread, throwable)
        }
        
        // Set up global coroutine exception handler
        // Note: This won't catch all coroutine exceptions, but it's a good safety net
        // CoroutineExceptionHandler only works for root coroutines (coroutines without a parent)
        GlobalScope.launch(coroutineExceptionHandler + Dispatchers.Default) {
            // This scope is just for the exception handler setup
        }
    }
    
    fun logErrorToFile(threadName: String, throwable: Throwable) {
        try {
            val errorLog = ErrorLog(
                timestamp = LocalDateTime.now(),
                threadName = threadName,
                exceptionType = throwable.javaClass.name,
                message = throwable.message ?: "No message",
                stackTrace = getStackTrace(throwable)
            )
            
            // Read existing logs
            val existingLogs = readErrorLogs()
            
            // Add new log (keep last 1000 errors to prevent file from growing too large)
            val updatedLogs = (existingLogs + errorLog).takeLast(1000)
            
            // Write back to file
            val jsonString = gson.toJson(updatedLogs)
            FileWriter(errorLogFile).use { writer ->
                writer.write(jsonString)
            }
            
            Log.d("MyApplication", "Error logged to file: ${errorLogFile.absolutePath}")
            
            // Send broadcast to trigger sync
            try {
                val intent = Intent(ERROR_LOGGED_ACTION).apply {
                    putExtra("error_count", updatedLogs.size)
                }
                sendBroadcast(intent)
            } catch (e: Exception) {
                Log.e("MyApplication", "Failed to send error logged broadcast", e)
            }
        } catch (e: Exception) {
            Log.e("MyApplication", "Failed to log error to file", e)
        }
    }
    
    companion object {
        const val ERROR_LOGGED_ACTION = "com.gabstra.myworkoutassistant.ERROR_LOGGED"
        private val resumedActivities = AtomicInteger(0)
        @Volatile private var isInForeground = false

        fun isAppInForeground(): Boolean = isInForeground
    }
    
    private fun readErrorLogs(): List<ErrorLog> {
        return try {
            if (errorLogFile.exists() && errorLogFile.length() > 0) {
                val jsonString = errorLogFile.readText()
                val type = object : TypeToken<List<ErrorLog>>() {}.type
                gson.fromJson<List<ErrorLog>>(jsonString, type) ?: emptyList()
            } else {
                emptyList()
            }
        } catch (e: Exception) {
            Log.e("MyApplication", "Failed to read error logs", e)
            emptyList()
        }
    }
    
    fun getErrorLogs(): List<ErrorLog> {
        return readErrorLogs()
    }
    
    fun clearErrorLogs() {
        try {
            if (errorLogFile.exists()) {
                errorLogFile.delete()
            }
        } catch (e: Exception) {
            Log.e("MyApplication", "Failed to clear error logs", e)
        }
    }
    
    private fun getStackTrace(throwable: Throwable): String {
        val sw = StringWriter()
        val pw = PrintWriter(sw)
        throwable.printStackTrace(pw)
        return sw.toString()
    }
}

