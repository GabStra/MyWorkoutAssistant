package com.gabstra.myworkoutassistant.shared.sets

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import java.util.UUID

data class BodyWeightSet(
    override val id: UUID,
    val reps: Int,
    val additionalWeight:Double,
    val subCategory: SetSubCategory = SetSubCategory.WorkSet,
    override val shouldReapplyHistoryToSet: Boolean = true
) : Set(id, shouldReapplyHistoryToSet){
    fun getWeight(relativeBodyWeight:Double): Double {
        return relativeBodyWeight + additionalWeight
    }
}
