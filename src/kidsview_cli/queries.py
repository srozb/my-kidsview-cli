"""Static GraphQL queries used by the CLI."""

USER_NOTIFICATION_PREFERENCES = """
query userNotificationPreferences {
  userNotificationPreferences {
    type
    name
    enabled
  }
}
"""

SET_USER_NOTIFICATION_PREFERENCES = """
mutation setUserNotificationPreferences($preferences: [NotificationPreferenceInput!]!) {
  setUserNotificationPreferences(preferences: $preferences) {
    success
  }
}
"""

SET_NOTIFICATION_READ = """
mutation setNotificationRead($notificationId: ID!) {
  setNotificationRead(notificationId: $notificationId) {
    success
  }
}
"""

QUICK_CALENDAR = """
query quickCalendar($groupsIds: [ID], $dateFrom: Date!, $dateTo: Date!) {
  quickCalendar(groupsIds: $groupsIds, dateFrom: $dateFrom, dateTo: $dateTo) {
    date
    hasEvents
    hasNewEvents
    holiday
    absent
    mealsModified
  }
}
"""

SCHEDULE = """
query schedule($group: ID!) {
  schedule(group: $group) {
    title
    groupsNames
    startDate
    endDate
    allDay
    id
    type
    color
    basicActivitySchedule
  }
}
"""

SET_CHILD_ABSENCE = """
mutation setChildAbsence(
  $childId: ID!
  $date: Date!
  $dateTo: Date
  $forcePartialMealRefund: Boolean
  $onTime: Boolean
  $partialMealRefund: Boolean
) {
  setChildAbsence(
    childId: $childId
    date: $date
    dateTo: $dateTo
    forcePartialMealRefund: $forcePartialMealRefund
    onTime: $onTime
    partialMealRefund: $partialMealRefund
  ) {
    success
  }
}
"""

PAYMENTS = """
query payments(
  $first: Int
  $after: String
  $dateFrom: Date
  $dateTo: Date
  $child: ID
  $type: String
  $isBooked: Boolean
) {
  payments(
    first: $first
    after: $after
    dateFrom: $dateFrom
    dateTo: $dateTo
    child: $child
    type: $type
    isBooked: $isBooked
  ) {
    edges {
      node {
        id
        title
        amount
        paymentDate
        type
        isBooked
        child { id name surname }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

SET_GALLERY_LIKE = """
mutation setGalleryLike($galleryId: ID!) {
  setGalleryLike(galleryId: $galleryId) {
    success
    isLiked
  }
}
"""

CREATE_GALLERY_COMMENT = """
mutation createGalleryComment($galleryId: ID!, $content: String!) {
  createGalleryComment(
    input: { gallery: $galleryId, content: $content }
  ) {
    errors
    galleryComment { id content }
  }
}
"""

CREATE_APPLICATION = """
mutation createApplication(
  $applicationFormId: ID!
  $commentParent: String
  $acceptContract: Boolean
  $months: Int
) {
  createApplication(
    input: {
      applicationFormId: $applicationFormId
      form: { commentParent: $commentParent, acceptContract: $acceptContract, months: $months }
    }
  ) {
    success
    error
    id
  }
}
"""

PAYMENT_ORDERS = """
query paymentOrders($first: Int, $after: String, $before: String, $offset: Int) {
  paymentOrders(first: $first, after: $after, before: $before, offset: $offset) {
    pageInfo { endCursor hasNextPage }
    edges {
      node {
        id
        created
        amount
        bluemediaOrderId
        bluemediaPaymentStatus
        bookingDate
      }
    }
  }
}
"""

PAYMENTS_SUMMARY = """
query paymentsSummary(
  $search: String
  $groupsIds: [ID]
  $interestAmountGte: Decimal
  $interestAmountLte: Decimal
  $balanceGte: Decimal
  $balanceLte: Decimal
  $paidMonthlyBillsCountGte: Int
  $paidMonthlyBillsCountLte: Int
) {
  paymentsSummary(
    search: $search
    groupsIds: $groupsIds
    interestAmountGte: $interestAmountGte
    interestAmountLte: $interestAmountLte
    balanceGte: $balanceGte
    balanceLte: $balanceLte
    paidMonthlyBillsCountGte: $paidMonthlyBillsCountGte
    paidMonthlyBillsCountLte: $paidMonthlyBillsCountLte
  ) {
    fullBalance
    children(first: 50) {
      edges {
        node {
          id
          name
          surname
          balance
          paidAmount
          amount
          paidMonthlyBillsCount
        }
      }
      pageInfo { endCursor hasNextPage }
    }
  }
}
"""

ANNOUNCEMENTS = """
query announcements($first: Int, $after: String, $status: AnnouncementStatus, $phrase: String) {
  announcements(first: $first, after: $after, status: $status, phrase: $phrase) {
    pageInfo { startCursor endCursor hasNextPage }
    edges {
      node {
        id
        title
        text
        expirationDate
        created
        read
        enableChatButton
        groups { edges { node { id name } } }
        createdBy { id fullName avatar userPosition }
        visibleForDirectors
        visibleForEmployees
        visibleForParents
        isChainAnnouncement
        attachmentUrls { id fileName url }
        readCount
        sentCount
      }
    }
  }
}
"""

MONTHLY_BILLS = """
query monthlyBills(
  $child: ID
  $isPaid: Boolean
  $year: String = ""
  $groups: [ID]
  $monthFrom: Date
  $monthTo: Date
  $isAccepted: Boolean
  $balanceGt: Float
  $balanceLt: Float
  $search: String
  $childContractActive: Boolean
  $after: String
  $first: Int
) {
  monthlyBills(
    child: $child
    isPaid: $isPaid
    year: $year
    groups: $groups
    monthFrom: $monthFrom
    monthTo: $monthTo
    isAccepted: $isAccepted
    search: $search
    childContractActive: $childContractActive
    balanceGt: $balanceGt
    balanceLt: $balanceLt
    first: $first
    after: $after
  ) {
    pageInfo { endCursor hasNextPage }
    totalBalance
    edges {
      node {
        id
        scheduledForRecalculation
        recalculationDate
        child { id avatar name surname technicalAccount balance group { id } }
        amount
        balance
        balanceWithoutOverpay
        interestAmount
        isAccepted
        fullAmount
        paidAmount
        paidAmountWithOverpay
        invoiceNumberList
        paymentDueTo
        billNumber
        acceptedDate
        isPaidToAdditionalAccount
        account { id accountName accountNumber }
        billingPeriod { id month { id startDate } }
      }
    }
  }
}
"""

GALLERIES = """
query galleries($groupId: String, $first: Int, $after: String, $search: String, $order: String) {
  galleries(group: $groupId, first: $first, after: $after, phrase: $search, order: $order) {
    edges {
      node {
        id
        name
        created
        description
        imagesCount
        paginatedImages(first: 9) {
          edges { node { id imageUrl imageUrlFull } }
        }
        videos { id videoUrl }
        comments {
          id
          content
          created
          isBlocked
          addedBy { id fullName avatar }
        }
        likes { id addedBy { id fullName } }
        meLike
        likesCount
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ACTIVE_CHILD_SUMMARY = """
query activeChild {
  activeChild {
    id
    name
    surname
    avatar
    status
    preschool { id name }
    preschoolAgreementsAccepted
    parents {
      edges {
        node {
          id
          firstName
          lastName
          phone
          avatar
          email
          idNumber
          hasAppAccess
          limitedAccess
          canPickupChild
          address
          city
          zipcode
          position
          loggedInSystem
          loggedInSystemDatetime
          isLegalGuardian
        }
      }
    }
  }
}
"""

ACTIVE_CHILD_DETAIL = """
query activeChild($dateFrom: Date!, $dateTo: Date!) {
  activeChild {
    id
    avatar
    name
    surname
    pesel
    birthdate
    birthplace
    officialAddress
    officialZipcode
    officialCity
    mailingAddress
    mailingZipcode
    mailingCity
    mailingMunicipality
    officialMunicipality
    contractStartDate
    contractEndDate
    exclusions { name id }
    dietCategory { name id }
    technicalAccount
    contractorBankAccount
    billingName
    billingCity
    issueInvoices
    kvIssueInvoices
    billingAddress
    billingBuildingNumber
    billingFlatNumber
    billingZipcode
    billingEmail
    billingPhone
    nip
    vatPayer
    useRecipient
    recipientName
    recipientCity
    recipientAddress
    recipientZipcode
    recipientNip
    recipientEmail
    recipientPhone
    recipientNumber
    useContractorNumber
    contractorNumber
    individualNumber
    preschoolAgreementsAccepted
    status
    balance
    mainAccountBalance
    additionalAccounts { accountName balanceForChild }
    currentInterest
    overpayAmount
    dayStartTimeAsNumber
    dayEndTimeAsNumber
    individualNumber
    hasAcceptedMonthlyBills
    galleryAccess
    pinCode
    contracts {
      edges {
        node {
          id
          deleted
          created
          modified
          contractStartDate
          contractEndDate
          isActive
          isIndefinite
        }
      }
    }
    alerts { field text }
    meals {
      edges {
        node {
          id
          enabled
          startDate
          endDate
          isIndefinite
          isActive
          meal { id name }
          paymentComponent { id name type }
        }
      }
    }
    mealPaymentComponents { edges { node { id name type } } }
    parents {
      edges {
        node {
          id
          firstName
          lastName
          phone
          avatar
          email
          idNumber
          hasAppAccess
          limitedAccess
          canPickupChild
          address
          city
          zipcode
          position
          loggedInSystem
          loggedInSystemDatetime
          isLegalGuardian
          workplace
          workPosition
          galleryAccess
          pinCode
        }
      }
    }
    dailyActivities(dateFrom: $dateFrom, dateTo: $dateTo) {
      edges {
        node {
          id
          date
          breakfast
          mainDish
          dinner
          tea
          napTime
          poo
          observation
          outdoorTime
          absence
          absenceReportedBy { id fullName }
          partiallyRefundMeals
          absenceReportedOnTime
          absenceReportedDatetime
          dropOffTime
          pickUpTime
          pickedUpBy { id idNumber firstName lastName }
          backpackItems {
            id
            addedBy { id fullName avatar customPositionName userPosition }
            description
            expirationDate
            isPacked
            enableChatButton
          }
        }
      }
    }
    preschool {
      name
      id
      avatar
      applyBillNumbering
      billNumberingIndividualTag
      billNumberingStartNumber
      billNumberingIsAnnual
      billNumberingStartMonth
      billNumberingStartYear
    }
    group { id name }
  }
}
"""

USERS_FOR_CHAT = """
query usersForChat($userTypes: [String]) {
  usersForChat(userTypes: $userTypes) {
    id
    chatDisplayName
    userType
    userPosition
    chatUserPosition
    avatar
    roleName
    firstName
    lastName
  }
}
"""

CHAT_THREADS = """
query threads(
  $first: Int
  $after: String
  $type: String
  $child: ID
  $preschool: ID
  $search: String
) {
  threads(
    first: $first
    after: $after
    type: $type
    child: $child
    preschool: $preschool
    search: $search
  ) {
    pageInfo { endCursor hasNextPage }
    edges {
      node {
        id
        name
        type
        modified
        lastMessage
        isRead
        recipients { id fullName }
        child { id name surname }
      }
    }
  }
}
"""

CHAT_MESSAGES = """
query thread($id: ID!, $first: Int, $after: String) {
  thread(id: $id) {
    id
    name
    type
    modified
    lastMessage
    recipients { id fullName }
    messages(first: $first, after: $after) {
      pageInfo { endCursor hasNextPage }
      edges {
        node {
          id
          text
          created
          read
          sender { id fullName }
        }
      }
    }
  }
}
"""

CURRENT_DIET = """
query currentDietForChild {
  currentDietForChild {
    id
    body
    category { id }
    attachments { edges { node { order id fileUrl } } }
  }
}
"""

ADDITIONAL_ACTIVITY_OBS = """
query fetchAdditionalActivityForChildRequest($childId: ID!, $id: ID) {
  additionalActivities(children: [$childId]) {
    edges {
      node {
        id
        name
        observations(child: $childId) {
          edges { node { id public } }
        }
      }
    }
  }
  child(id: $childId) {
    additionalActivityObservations(additionalActivity: $id) {
      edges {
        node {
          id
          public
          additionalActivity { id name }
        }
      }
    }
  }
}
"""

APPLICATIONS = """
query applications($phrase: String, $status: String) {
  applications(phrase: $phrase, status: $status) {
    edges {
      node {
        id
        created
        applicationForm {
          id
          name
          status
          applicationSubmissionDeadline
          additionalActivity { id name }
        }
        status
        commentDirector
      }
    }
  }
}
"""

NOTIFICATIONS = """
query notifications($first: Int, $after: String, $pending: Boolean) {
  notifications(first: $first, after: $after, pending: $pending) {
    pageInfo { startCursor endCursor hasNextPage }
    edges {
      node {
        id
        title
        text
        target
        created
        isRead
        notifyOn
        relatedId
        type
        isPostponed
        notification { id }
        data
      }
    }
  }
}
"""

YEARS = """
query years {
  years {
    id
    displayName
    startDate
    endDate
  }
}
"""

GROUPS_FOR_CHAT = """
query groupsForChat($search: String) {
  groupsForChat(search: $search) {
    id
    name
    children {
      id
      fullName
      avatarUrl
      parents {
        id
        chatDisplayName
        avatarUrl
        positionName
      }
    }
  }
}
"""

CREATE_THREAD = """
mutation createThread($input: CreateThreadInput!) {
  createThread(input: $input) {
    success
    error
    id
  }
}
"""

ME = """
query me {
  me {
    id
    subclassId
    firstName
    lastName
    fullName
    email
    phone
    address
    zipcode
    city
    pesel
    employmentDate
    employeeTosAccepted
    employeePrivacyPolicyAccepted
    medicalExaminationsValidUntil
    ohsTrainingValidUntil
    firstAidCourseValidUntil
    vacationDaysTotal
    customPositionName
    memberOfGuardiansPersonnelChats
    alerts { field text }
    availablePreschools {
      id
      avatar
      name
      address
      zipcode
      city
      voivodeship
      county
      district
      phone
      email
      nip
      registerCode
      transferCode
      bankAccount
      blockEditBankAccount
      archiveAnnouncements
      preschoolCode
      sellerOption
      customSellerName
      customSellerAddress
      customSellerZipcode
      customSellerCity
      customSellerNip
      dataAdminOption
      customDataAdminName
      customDataAdminAddress
      customDataAdminZipcode
      customDataAdminCity
      absenceDeadlineDaysBefore
      absenceDeadlineHour
      mealRefundDeadlineDaysBefore
      mealRefundDeadlineHour
      displayDropOffAndPickUpTime
      billingPeriodRecalculation
      galleryComments
      registeredPickup
      paymentDay
      paymentDayOption
      paymentDayAfterInvoice
      accrueInterest
      interestAmount
      pinCodeAttendanceEnabled
      preschoolChain { organisationName }
      currentCurriculum {
        id
        name
        year
        developmentAreaItems {
          edges {
            node {
              id
              description
              ordinalNumber
              curriculumCoreOrdinalNumber
              achievements { edges { node { id description ordinalNumber } } }
            }
          }
        }
      }
      keyCompetences: keyCompetencesPreschoolAssociation { id name }
      additionalAccounts {
        edges {
          node {
            id
            accountName
            accountNumber
            isReadyToDelete
            isAdditionalSeller
            sellerName
            sellerAddress
            sellerCity
            sellerZipcode
            sellerNip
            additionalSellerBilling {
              applyBillNumbering
              billNumberingIndividualTag
              billNumberingIndividualTagSeparator
              billNumberingStartNumber
              billNumberingIsAnnual
              billNumberingStartMonth
              billNumberingStartYear
              billNumberingSuffix
              billNumberingSuffixSeparator
              applyInvoiceNumbering
              invoiceNumberingIndividualTag
              invoiceNumberingIndividualTagSeparator
              invoiceStartNumber
              invoiceNumberingIsAnnual
              invoiceNumberingStartMonth
              invoiceNumberingStartYear
              invoiceNumberingSuffix
              invoiceNumberingSuffixSeparator
              correctionNumberingIndividualTag
              correctionNumberingIndividualTagSeparator
              correctionStartNumber
              correctionNumberingIsAnnual
              correctionNumberingStartMonth
              correctionNumberingStartYear
              correctionNumberingSuffix
              correctionNumberingSuffixSeparator
            }
          }
        }
      }
      paymentReminderEmailSubject
      paymentReminderEmailContent
      showAdditionalActivitiesParents
      showAdditionalActivitiesEmployees
      showIndividualActivitiesParents
      showIndividualActivitiesEmployees
      parentsCanMessageParents
      parentsCanMessagePersonnel
      parentsCanAddGuardians
      parentsCustomPermissions { code }
      displayIndividualActivitiesForParents
      displayAttendanceForParents
      displayActivityBillingDetailsForParents
      employeesSeeMessagesForModeration
      guardiansPersonnelGroupChats
      disableBankTransferPayments
      applyBillNumbering
      billNumberingIndividualTag
      billNumberingIndividualTagSeparator
      billNumberingStartNumber
      billNumberingIsAnnual
      billNumberingStartMonth
      billNumberingStartYear
      billNumberingSuffix
      billNumberingSuffixSeparator
      applyInvoiceNumbering
      invoiceNumberingIndividualTag
      invoiceNumberingIndividualTagSeparator
      invoiceStartNumber
      invoiceNumberingIsAnnual
      invoiceNumberingStartMonth
      invoiceNumberingStartYear
      invoiceNumberingSuffix
      invoiceNumberingSuffixSeparator
      invoiceText
      correctionNumberingIndividualTag
      correctionNumberingIndividualTagSeparator
      correctionStartNumber
      correctionNumberingIsAnnual
      correctionNumberingStartMonth
      correctionNumberingStartYear
      correctionNumberingSuffix
      correctionNumberingSuffixSeparator
      employeeFeeName
      employeeFeeRate
      dayStartTime
      dayEndTime
      dayStartTimeAsNumber
      dayEndTimeAsNumber
      autoSetTeaHour
      autoSetDinnerHour
      autoSetBreakfastHour
      autoSetDailyActivities
      advencedMealsRating
      invoiceSetType
      directors { fullName }
      aboutAppPage
      termsOfUsePage
      privacyPolicyPage
      employeeRoles { edges { node { id name permissions } } }
      employees { edges { node { id position role { id name } } } }
      years {
        edges {
          node {
            id
            startDate
            isOpen
            displayName
            months {
              id
              monthNumber
              startDate
              endDate
              isActive
              isCurrent
              year { id yearNumber }
            }
          }
        }
      }
      mealsDailyManagement
      mealsDailyManagementParent
      displaySubjectsForParents
      mealReportEmail
      mealReportEmailSubject
      mealReportEmailBody
      mealReportTime
      mealReportSchedule
      secondMealReportTime
      secondMealReportSchedule
      canGenerateQrCode
      extendedMealSystem
      meals { id name excludedFromPartialRefund }
      institutionType
      fullWeekCalendar
    }
    availablePreschoolChains { id name avatar }
    permissions
    avatar
    userPosition
    userType
    unreadNotificationsCount
    unreadMessagesCount
    tosAccepted
    marketingAgreementAccepted
    appLoggedIn
    calendarNotificationsEnabled
    paymentNotificationsEnabled
    behaviorNotificationsEnabled
    announcementNotificationsEnabled
    messageNotificationsEnabled
    galleryNotificationsEnabled
    appHomeScreen
    children {
      name
      surname
      avatar
      group { id name }
      id
      avatar
    }
    subAccounts { id subAccountDescription }
    eduManagerBlogEditor
    dayStartTime
    dayEndTime
  }
}
"""

COLORS = """
query colors {
  me {
    availablePreschools {
      id
      usercolorSet {
        headerColor
        backgroundColor
        accentColor
        highlightColor
        inputColor
      }
    }
  }
}
"""

UNREAD_COUNTS = """
query unreadCounts {
  me {
    unreadNotificationsCount
    unreadMessagesCount
  }
}
"""

CALENDAR = """
query calendar(
  $groupsIds: [ID]
  $dateFrom: Date!
  $dateTo: Date!
  $activityTypes: [Int]
  $showCanceledActivities: Boolean
  $forSchedule: Boolean
  $activityId: ID
) {
  calendar(
    groupsIds: $groupsIds
    dateFrom: $dateFrom
    dateTo: $dateTo
    activityTypes: $activityTypes
    showCanceledActivities: $showCanceledActivities
    forSchedule: $forSchedule
    activityId: $activityId
  ) {
    title
    startDate
    endDate
    id
    allDay
    type
    color
    hideAsDefault
    groupsNames
    isCanceled
    internalOnlineUrl
    effectiveOnlineUrl
    useGroupLink
    absenceReportedBy { id fullName }
    absenceReportedOnTime
    absenceReportedDatetime
    mealsModifiedDatetime
    mealsModifiedBy { id firstName lastName }
    lesson {
      name
      id
      specificSubject { id name }
      note
      activityType
      courseOfLesson
      shortTranscript
      attachments { edges { node { file fileUrl id attachmentType } } }
    }
  }
}
"""
