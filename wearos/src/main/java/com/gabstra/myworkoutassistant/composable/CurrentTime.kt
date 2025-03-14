package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
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

import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight

@SuppressLint("DefaultLocale")
@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    var showColon by remember { mutableStateOf(true) }

    // Coroutine that updates the time every minute
    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            currentTime = now
            showColon = !showColon
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
        }
    }

    Row(
        modifier = Modifier.width(50.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            modifier = Modifier.weight(1f),
            text = String.format("%02d", currentTime.hour),
            style = MaterialTheme.typography.caption1,
            textAlign = TextAlign.End
        )

        Text(
            text = ":",
            style = MaterialTheme.typography.caption1,
            color = if (showColon) Color.White else Color.DarkGray,
            textAlign = TextAlign.Center
        )

        Text(
            modifier = Modifier.weight(1f),
            text = String.format("%02d", currentTime.minute),
            style = MaterialTheme.typography.caption1,
            textAlign = TextAlign.Start
        )
    }
}
