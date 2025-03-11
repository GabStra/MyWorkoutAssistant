package com.gabstra.myworkoutassistant.composable

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import java.time.temporal.ChronoUnit
import androidx.compose.animation.core.animateColorAsState
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.layout.Row

@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    // Coroutine that updates the time every minute
    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            currentTime = now
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
        }
    }

    var showColon by remember { mutableStateOf(true) }
    val colonColor by animateColorAsState(
        targetValue = if (showColon) Color.White else Color.DarkGray,
        animationSpec = tween(durationMillis = 500)
    )

    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            currentTime = now
            showColon = !showColon
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
        }
    }

    Row {
        Text(
            text = String.format("%02d", currentTime.hour),
            style = MaterialTheme.typography.caption1
        )
        Text(
            text = ":",
            style = MaterialTheme.typography.caption1,
            color = colonColor
        )
        Text(
            text = String.format("%02d", currentTime.minute),
            style = MaterialTheme.typography.caption1
        )
    }
}
