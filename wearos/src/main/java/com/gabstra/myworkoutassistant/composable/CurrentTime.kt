package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import java.time.temporal.ChronoUnit

import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import com.gabstra.myworkoutassistant.presentation.theme.MyColors

@SuppressLint("DefaultLocale")
@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    var showDots by remember { mutableStateOf(true) }

    // Coroutine that updates the time every minute
    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            currentTime = now
            showDots = !showDots
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
        }
    }

    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(1.dp)
    ) {
        Text(
            modifier = Modifier.fillMaxHeight(),
            text = String.format("%02d", currentTime.hour),
            style = MaterialTheme.typography.caption1,
            textAlign = TextAlign.End
        )

        ClockSeparator(
            showDots = showDots,
            modifier = Modifier
                .width(6.dp)
                .fillMaxHeight()
        )

        Text(
            modifier = Modifier.fillMaxHeight(),
            text = String.format("%02d", currentTime.minute),
            style = MaterialTheme.typography.caption1,
            textAlign = TextAlign.Start
        )
    }
}

@Composable
fun ClockSeparator(
    showDots: Boolean,
    modifier: Modifier = Modifier
) {
    Canvas(modifier = modifier) {
        val dotRadius = size.height / 12f
        val centerX = size.width / 2f
        val centerY = size.height / 2f
        val gap = size.height / 5f
        val color = if (showDots) Color.White else MyColors.LightGray

        drawCircle(
            color = color,
            radius = dotRadius,
            center = Offset(centerX, centerY - gap)
        )
        drawCircle(
            color = color,
            radius = dotRadius,
            center = Offset(centerX, centerY + gap)
        )
    }
}