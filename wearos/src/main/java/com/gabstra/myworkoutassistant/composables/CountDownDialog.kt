package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text

@Composable
fun CountDownDialog(
    show: Boolean,
    time: Int,
) {
    val typography = MaterialTheme.typography

    if(show) {
        Dialog(
            onDismissRequest = { },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false)
        ) {
            Box(
                modifier = Modifier
                    .background(MaterialTheme.colors.background.copy(alpha = 0.75f))
                    .fillMaxSize()
                    .padding(20.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "$time",
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.title1.copy(fontSize = MaterialTheme.typography.title1.fontSize * 1.625f,fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace),
                )
            }
        }
    }
}