package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@Composable
fun TimeViewer(
    modifier: Modifier = Modifier,
    seconds: Int,
    color: Color,
    style: TextStyle,
) {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60

    var showDots by remember { mutableStateOf(true) }

    // Coroutine that updates the time every minute
    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            showDots = !showDots
            val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
            delay(java.time.Duration.between(now, nextSecond).toMillis())
        }
    }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {

        if(hours > 0){
            Text(
                modifier = Modifier,
                text = String.format("%02d", hours),
                style = style,
                textAlign = TextAlign.Center,
                color =  color,
            )

            Text(
                text = ":",
                style = style,
                color = if (showDots) color else MaterialTheme.colorScheme.background,
                textAlign = TextAlign.Center,
            )
        }

        Text(
            modifier = Modifier,
            text = String.format("%02d", minutes),
            style = style,
            textAlign = TextAlign.Center,
            color =  color,
        )

        Text(
            text = ":",
            style = style,
            color = if (showDots) color else MaterialTheme.colorScheme.background,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(bottom = 3.dp),
        )

        Text(
            modifier = Modifier,
            text = String.format("%02d", remainingSeconds),
            style = style,
            textAlign = TextAlign.Center,
            color =  color,
        )
    }
}