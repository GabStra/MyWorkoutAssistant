package com.gabstra.myworkoutassistant.composable

import androidx.compose.runtime.Composable
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import java.time.LocalDateTime

@Composable
fun CurrentTime(){
    val now = LocalDateTime.now()

    Text(
        text = String.format("%02d:%02d", now.hour, now.minute),
        style = MaterialTheme.typography.caption1
    )
}