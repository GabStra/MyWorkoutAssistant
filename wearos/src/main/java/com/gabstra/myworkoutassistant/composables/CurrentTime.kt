package com.gabstra.myworkoutassistant.composables

import android.R.attr.digits
import android.annotation.SuppressLint
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    var showDots by remember { mutableStateOf(true) }

    val captionStyle =  MaterialTheme.typography.labelSmall

    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val twoDigitWidth = remember(digits, density) {
        with(density) { measurer.measure("00", style = captionStyle).size.width.toDp() }
    }

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
        horizontalArrangement = Arrangement.spacedBy(1.5.dp)
    ) {
        Text(
            modifier = Modifier.width(twoDigitWidth),
            text = String.format("%02d", currentTime.hour),
            style = captionStyle,
            textAlign = TextAlign.Center,
        )

        Text(
            text = ":",
            style = captionStyle,
            color = if (showDots) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.surfaceContainer,
        )

        Text(
            modifier = Modifier.width(twoDigitWidth),
            text = String.format("%02d", currentTime.minute),
            style = captionStyle,
            textAlign = TextAlign.Center,
        )
    }
}


