package com.gabstra.myworkoutassistant.composable


import androidx.compose.material.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material.MaterialTheme
import kotlinx.coroutines.delay

@Composable
fun LoadingText(baseText: String) {
    // State to hold the count of dots
    val dotCount = remember { mutableStateOf(0) }

    // Coroutine to update dot count
    LaunchedEffect(key1 = Unit) {
        while (true) {
            delay(500) // Delay between dot updates
            dotCount.value = (dotCount.value + 1) % 4 // Loop back after 3 dots
        }
    }

    // Compose the text with dynamic dots
    Text(
        text = "$baseText" + ".".repeat(dotCount.value),
        textAlign = TextAlign.Center,
        style = MaterialTheme.typography.title3,
        color = Color.White
    )
}
