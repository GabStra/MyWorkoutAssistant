package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.shared.LighterGray
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.gabstra.myworkoutassistant.shared.MediumLighterGray

/** A section with a title and a list of lines (e.g. "Equipment" / ["Barbell"] or "Accessories" / ["Bench", "Rings"]). */
data class TitledLinesSection(val title: String, val lines: List<String>)

@Composable
private fun TitledLinesSectionItem(
    section: TitledLinesSection,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier) {
        Text(
            text = section.title,
            modifier = Modifier.fillMaxWidth(),
            style = workoutPagerTitleTextStyle(),
            fontWeight = FontWeight.Bold,
            color = LighterGray,
            textAlign = TextAlign.Center
        )
        section.lines.forEach { line ->
            Text(
                text = line,
                modifier = Modifier.padding(top = 5.dp).fillMaxWidth(),
                style = MaterialTheme.typography.bodyLarge,
                color = MediumLighterGray,
                textAlign = TextAlign.Center
            )
        }
    }
}

/**
 * Full-screen scrollable page that shows a list of sections, each with a bold title and lines.
 * No buttons; navigation/dismiss is handled by the parent (e.g. back gesture).
 * Use for content like "Equipment: Barbell" and "Accessories: Bench, Rings".
 */
@Composable
fun PageTitledLines(
    sections: List<TitledLinesSection>,
    modifier: Modifier = Modifier
) {
    val state = rememberTransformingLazyColumnState()
    val spec = rememberTransformationSpec()

    ScreenScaffold(
        modifier = modifier.fillMaxSize(),
        scrollState = state,
        scrollIndicator = {
            ScrollIndicator(
                state = state,
                colors = ScrollIndicatorDefaults.colors(
                    indicatorColor = MaterialTheme.colorScheme.onBackground,
                    trackColor = MediumDarkGray
                )
            )
        }
    ) { contentPadding ->
        TransformingLazyColumn(
            contentPadding = contentPadding,
            state = state
        ) {
            sections.forEach { section ->
                item{
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                    ) {
                        TitledLinesSectionItem(
                            section = section,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }
            }
        }
    }
}
