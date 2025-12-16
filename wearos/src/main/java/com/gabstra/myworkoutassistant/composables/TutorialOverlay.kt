package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar

/**
 * Converts tutorial text string to AnnotatedString with proper styling.
 * Tutorial text follows the pattern: sections separated by \n\n,
 * where each section has a title on the first line followed by description lines.
 *
 * @param text The tutorial text string to convert
 * @param titleFontSize The font size to use for titles (typically titleSmall.fontSize)
 * @param bodyFontSize The font size to use for descriptions (typically bodySmall.fontSize)
 * @return AnnotatedString with titles styled as bold with titleSmall size and descriptions as bodySmall
 */
@Composable
private fun formatTutorialText(
    text: String,
    titleFontSize: androidx.compose.ui.unit.TextUnit = MaterialTheme.typography.titleSmall.fontSize,
    bodyFontSize: androidx.compose.ui.unit.TextUnit = MaterialTheme.typography.bodySmall.fontSize
): AnnotatedString {
    return buildAnnotatedString {
        val sections = text.split("\n\n")
        
        sections.forEachIndexed { sectionIndex, section ->
            if (sectionIndex > 0) {
                // Add spacing between sections
                append("\n\n")
            }
            
            val lines = section.split("\n")
            if (lines.isNotEmpty()) {
                // First line is the title
                val title = lines[0]
                val description = lines.drop(1).joinToString("\n")
                
                // Add title with bold titleSmall style
                withStyle(
                    style = SpanStyle(
                        fontWeight = FontWeight.Bold,
                        fontSize = titleFontSize
                    )
                ) {
                    append(title)
                }
                
                // Add description with bodySmall style (if present)
                if (description.isNotEmpty()) {
                    append("\n")
                    withStyle(
                        style = SpanStyle(
                            fontSize = bodyFontSize
                        )
                    ) {
                        append(description)
                    }
                }
            }
        }
    }
}

/**
 * Simple dimmed overlay used as a lightweight "coach-mark" style tutorial.
 *
 * This is intentionally generic so it can be reused on multiple screens.
 * Tutorial text is automatically formatted with titles in bold and descriptions in regular text.
 */
@Composable
fun TutorialOverlay(
    visible: Boolean,
    text: String,
    modifier: Modifier = Modifier,
    onDismiss: () -> Unit,
    buttonText: String = "Got it"
) {
    AnimatedVisibility(
        visible = visible,
        enter = fadeIn(),
        exit = fadeOut()
    ) {
        Box(
            modifier = modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background),
            contentAlignment = Alignment.Center
        ) {
            ScreenScaffold(
                modifier = Modifier.fillMaxSize()
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(25.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    val scrollState = rememberScrollState()
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth()
                            .verticalColumnScrollbar(scrollState = scrollState)
                            .verticalScroll(scrollState),
                        contentAlignment = Alignment.Center
                    ) {
                        val annotatedText = formatTutorialText(text)
                        Text(
                            modifier = Modifier.padding(horizontal = 10.dp),
                            text = annotatedText,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onBackground,
                            textAlign = TextAlign.Center
                        )
                    }

                    // Fixed button at the bottom
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(),
                        contentAlignment = Alignment.Center
                    ) {
                        Button(
                            onClick = onDismiss,
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 5.dp)
                        ) {
                            Text(
                                text = buttonText,
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Center
                            )
                        }
                    }
                }
            }
        }
    }
}

