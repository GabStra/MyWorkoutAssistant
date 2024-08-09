package com.gabstra.myworkoutassistant.composable

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import android.os.BatteryManager
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import java.time.temporal.ChronoUnit

private fun getInitialBatteryPercentage(context: Context): Int {
    val batteryStatus: Intent? = IntentFilter(Intent.ACTION_BATTERY_CHANGED).let { ifilter ->
        context.registerReceiver(null, ifilter)
    }
    return getBatteryPercentage(batteryStatus)
}

private fun getBatteryPercentage(intent: Intent?): Int {
    val level: Int = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
    val scale: Int = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
    return if (level != -1 && scale != -1) {
        (level.toFloat() / scale.toFloat() * 100f).toInt()
    } else {
        0
    }
}

@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    val context = LocalContext.current
    var batteryPercentage by remember { mutableIntStateOf(getInitialBatteryPercentage(context)) }

    DisposableEffect(context) {
        val batteryReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                if (intent?.action == Intent.ACTION_BATTERY_CHANGED) {
                    batteryPercentage = getBatteryPercentage(intent)
                }
            }
        }

        context.registerReceiver(batteryReceiver, IntentFilter(Intent.ACTION_BATTERY_CHANGED))

        onDispose {
            context.unregisterReceiver(batteryReceiver)
        }
    }

    // Coroutine that updates the time every minute
    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            currentTime = now
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
        }
    }


    // Display the time
    Text(
        modifier = Modifier.padding(0.dp,5.dp,0.dp,0.dp),
        textAlign = TextAlign.Center,
        text = String.format("%d%% %02d:%02d", batteryPercentage, currentTime.hour, currentTime.minute),
        style = MaterialTheme.typography.caption1
    )
}
