package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
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
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.shared.LightGray
import com.gabstra.myworkoutassistant.shared.MediumGray
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

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
            textAlign = TextAlign.Center,
            color =  LightGray,
        )

        Text(
            text = ":",
            style = MaterialTheme.typography.caption1,
            color = if (showDots) LightGray else MediumGray,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxHeight(),
        )

        Text(
            modifier = Modifier.fillMaxHeight(),
            text = String.format("%02d", currentTime.minute),
            style = MaterialTheme.typography.caption1,
            textAlign = TextAlign.Center,
            color =  LightGray,
        )
    }
}


