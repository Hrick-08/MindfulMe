// Main JavaScript file for MindfulMe

document.addEventListener("DOMContentLoaded", () => {
  // Mobile navigation toggle
  const mobileNavToggle = document.createElement("button")
  mobileNavToggle.classList.add("mobile-nav-toggle")
  mobileNavToggle.innerHTML = "☰"

  const header = document.querySelector("header")
  const nav = document.querySelector("nav")

  if (header && nav && window.innerWidth < 768) {
    header.insertBefore(mobileNavToggle, nav)
    nav.style.display = "none"

    mobileNavToggle.addEventListener("click", () => {
      if (nav.style.display === "none") {
        nav.style.display = "block"
        mobileNavToggle.innerHTML = "✕"
      } else {
        nav.style.display = "none"
        mobileNavToggle.innerHTML = "☰"
      }
    })
  }

  // Flash message auto-dismiss
  const flashMessages = document.querySelectorAll(".flash-message")
  flashMessages.forEach((message) => {
    setTimeout(() => {
      message.style.opacity = "0"
      setTimeout(() => {
        message.style.display = "none"
      }, 500)
    }, 5000)
  })

  // Add smooth scrolling to all links
  document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
    anchor.addEventListener("click", function (e) {
      e.preventDefault()

      const target = document.querySelector(this.getAttribute("href"))
      if (target) {
        target.scrollIntoView({
          behavior: "smooth",
        })
      }
    })
  })

  // Add responsive styles for tables
  document.querySelectorAll("table").forEach((table) => {
    const wrapper = document.createElement("div")
    wrapper.classList.add("table-responsive")
    table.parentNode.insertBefore(wrapper, table)
    wrapper.appendChild(table)
  })
})

// Function to format dates
function formatDate(date) {
  const options = { year: "numeric", month: "long", day: "numeric" }
  return new Date(date).toLocaleDateString(undefined, options)
}

// Function to format times
function formatTime(date) {
  const options = { hour: "2-digit", minute: "2-digit" }
  return new Date(date).toLocaleTimeString(undefined, options)
}

// Function to handle form validation
function validateForm(form) {
  let isValid = true

  form.querySelectorAll("[required]").forEach((field) => {
    if (!field.value.trim()) {
      isValid = false
      field.classList.add("error")

      // Add error message if it doesn't exist
      let errorMessage = field.parentNode.querySelector(".error-message")
      if (!errorMessage) {
        errorMessage = document.createElement("div")
        errorMessage.classList.add("error-message")
        errorMessage.textContent = "This field is required"
        field.parentNode.appendChild(errorMessage)
      }
    } else {
      field.classList.remove("error")
      const errorMessage = field.parentNode.querySelector(".error-message")
      if (errorMessage) {
        errorMessage.remove()
      }
    }
  })

  return isValid
}

// Add event listeners to forms
document.querySelectorAll("form").forEach((form) => {
  form.addEventListener("submit", function (e) {
    if (!validateForm(this)) {
      e.preventDefault()
    }
  })
})

