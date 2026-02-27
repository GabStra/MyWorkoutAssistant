package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.MaterialTheme

@Composable
fun ExerciseNameText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.titleLarge.copy(
        fontWeight = FontWeight.SemiBold
    ),
    textAlign: TextAlign = TextAlign.Center,
) {
    ExerciseNameText(
        text = AnnotatedString(text),
        modifier = modifier,
        style = style,
        textAlign = textAlign,
    )
}

@Composable
fun ExerciseNameText(
    text: AnnotatedString,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.titleLarge.copy(
        fontWeight = FontWeight.SemiBold
    ),
    textAlign: TextAlign = TextAlign.Center,
) {
    FadingText(
        modifier = modifier,
        text = text,
        style = style,
        textAlign = textAlign,
    )
}
