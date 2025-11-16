package com.gabstra.myworkoutassistant.shared.sets

import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import java.util.UUID

data class WeightSet(override val id: UUID, val reps: Int, val weight: Double, val subCategory: SetSubCategory = SetSubCategory.WorkSet) : Set(id){
}
