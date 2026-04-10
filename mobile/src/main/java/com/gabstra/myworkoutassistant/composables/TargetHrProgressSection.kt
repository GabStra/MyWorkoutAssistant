package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.MediumDarkGray
import com.kevinnzou.compose.progressindicator.SimpleProgressIndicator

/**
 * Target heart-rate band summary (range, time-in-zone %, progress bar) used on exercise and
 * workout history set tabs.
 */
@Composable
fun TargetHrProgressSection(
    targetCounter: Int,
    targetTotal: Int,
    lowHrBpm: Int,
    highHrBpm: Int,
    modifier: Modifier = Modifier,
    progressBarColor: Color = Color.hsl(113f, 0.79f, 0.34f),
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(10.dp),
    ) {
        val rawProgress = targetCounter.toFloat() / targetTotal
        val progress = if (rawProgress.isNaN()) 0f else rawProgress

        Text(
            text = "Target HR",
            color = MaterialTheme.colorScheme.onBackground,
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(5.dp))
        Row(modifier = Modifier.fillMaxWidth()) {
            Text(
                "$lowHrBpm - $highHrBpm bpm",
                Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onBackground,
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.weight(1f))
            Text(
                text = "${(progress * 100).toInt()}% ${formatTime(targetCounter)}",
                Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.End,
                color = MaterialTheme.colorScheme.onBackground,
            )
        }
        Spacer(Modifier.height(5.dp))
        SimpleProgressIndicator(
            progress = progress,
            trackColor = MediumDarkGray,
            modifier = Modifier
                .fillMaxWidth()
                .height(16.dp)
                .clip(MaterialTheme.shapes.large),
            progressBarColor = progressBarColor,
        )
    }
}
