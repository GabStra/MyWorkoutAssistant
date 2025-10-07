package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import android.os.SystemClock
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import java.time.LocalDateTime

@SuppressLint("DefaultLocale")
@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    var showDots by remember { mutableStateOf(true) }

    val captionStyle =  MaterialTheme.typography.labelSmall

    LaunchedEffect(Unit) {
        var nextTick = ((SystemClock.elapsedRealtime() / 1000) + 1) * 1000 // round UP to next second
        while (isActive) {
            val wait = (nextTick - SystemClock.elapsedRealtime()).coerceAtLeast(0L)
            delay(wait)

            // update UI state on each tick
            currentTime = LocalDateTime.now()  // for display
            showDots = !showDots

            nextTick += 1000
        }
    }

    Row(
        modifier = Modifier.fillMaxHeight(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(1.5.dp)
    ) {
        Text(
            text = String.format("%02d", currentTime.hour),
            style = captionStyle,
            textAlign = TextAlign.Center,
        )

        Text(
            text = ":",
            style = captionStyle,
            color = if (showDots) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.background,
        )

        Text(
            text = String.format("%02d", currentTime.minute),
            style = captionStyle,
            textAlign = TextAlign.Center,
        )
    }
}


