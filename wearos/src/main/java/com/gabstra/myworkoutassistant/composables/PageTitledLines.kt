package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.items
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.ScrollIndicator
import androidx.wear.compose.material3.ScrollIndicatorDefaults
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.ResponsiveTransformationSpec
import androidx.wear.compose.material3.lazy.TransformationVariableSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import java.util.Locale.getDefault

/** A section with a title and a list of lines (e.g. "Equipment" / ["Barbell"] or "Accessories" / ["Bench", "Rings"]). */
data class TitledLinesSection(val title: String, val lines: List<String>)

@Composable
private fun TitledLinesSectionItem(
    section: TitledLinesSection,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier,
    ) {
        Text(
            text = section.title.uppercase(getDefault()),
            modifier = Modifier.fillMaxWidth(),
            style = workoutPagerTitleTextStyle(),
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center
        )
        section.lines.forEach { line ->
            Text(
                text = line,
                modifier = Modifier.padding(top = 5.dp).fillMaxWidth(),
                style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold),
                color = MaterialTheme.colorScheme.onBackground,
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
    val spec = rememberTransformationSpec(
        ResponsiveTransformationSpec.smallScreen(
            containerAlpha = TransformationVariableSpec(1f),
            contentAlpha = TransformationVariableSpec(1f),
            scale = TransformationVariableSpec(0.75f)
        ),
        ResponsiveTransformationSpec.largeScreen(
            containerAlpha = TransformationVariableSpec(1f),
            contentAlpha = TransformationVariableSpec(1f),
            scale = TransformationVariableSpec(0.6f)
        )
    )

    ScreenScaffold(
        modifier = modifier,
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
            state = state,
            modifier = Modifier.padding(horizontal = 25.dp),
            contentPadding = WorkoutPagerPageSafeAreaPadding,
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            items(sections) { section ->
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .transformedHeight(this, spec)
                        .graphicsLayer { with(spec) { applyContainerTransformation(scrollProgress) } }
                ) {
                    Column(
                        modifier = Modifier.graphicsLayer {
                            with(spec) { applyContentTransformation(scrollProgress) }
                        }
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
