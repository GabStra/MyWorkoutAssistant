package com.gabstra.myworkoutassistant.composables

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

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
fun CurrentBattery(){
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

    Text(
        textAlign = TextAlign.Center,
        text = String.format("%d%%", batteryPercentage),
        style = MaterialTheme.typography.caption1
    )
}