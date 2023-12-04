package com.gabstra.myworkoutassistant.composable

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime

@Composable
fun CurrentTime() {
    // State for holding current time
    val currentTime = remember { mutableStateOf(LocalDateTime.now()) }

    // Coroutine that updates the time every minute
    LaunchedEffect(Unit) {
        while (true) {
            currentTime.value = LocalDateTime.now()
            delay(60_000) // Delay for 60 seconds
        }
    }

    // Display the time
    Text(
        text = String.format("%02d:%02d", currentTime.value.hour, currentTime.value.minute),
        style = MaterialTheme.typography.caption1
    )
}
